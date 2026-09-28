# A.T.I.D.E. - Autonomous & Teleoperated Intervention in Degraded Environments

An agent runtime for autonomous rover fault recovery: a ROS 2 / Gazebo navigation pipeline that detects
sensor faults live, reasons about the best recovery action using retrieval-augmented LLM reasoning, and
acts on that decision, with the reasoning itself surfaced, not hidden.

Built for the [Nebius x NVIDIA Global AI Hackathon](https://nebiusglobalaihackathon.devpost.com/)
(Physical AI Track).

## The problem

Autonomous inspection and survey rovers operate in environments where sensor faults are expected, not
exceptional, like tunnels, collapsed structures, planetary caves. When a LiDAR drops out, a conventional
rule-based system does the safest thing it knows: halt. That's correct behavior *if the fault is
unrecoverable*. But it's the wrong response to an intermittent glitch that would clear in a second, and
it's the wrong response to a fault whose cause is a misconfiguration rather than hardware failure.

A.T.I.D.E. shows what changes when the recovery decision is made by a reasoning agent rather than a
table of `if/else`. The agent retrieves current recovery guidance, weighs the options against the actual
fault condition, and explains *why*, with the full reasoning trace surfaced live. A hardcoded baseline
runs the identical scenario side by side, so the difference is measurable, not asserted.

## What this is

A rover navigates a confined tunnel in Gazebo Harmonic using Nav2. Mid-run, a fault-injection node
degrades the simulated LiDAR feed, a full dropout or an intermittent, sparse signal. Instead of halting
on any sensor problem, a diagnostics agent retrieves relevant ROS 2 fault-recovery knowledge via
**Tavily**, reasons over it with **NVIDIA Nemotron 3 Nano** on **Nebius Token Factory**, and decides:
`RETRY_NAVIGATION`, `REVERSE_AND_REPLAN`, or `HALT`. A recovery executor acts on that decision. The
reasoning trace is captured and published alongside the decision, so the decision is auditable rather
than opaque.

## Built With

- **Nebius Token Factory** - hosts the inference endpoint for every reasoning call
- **NVIDIA Nemotron 3 Nano** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) - the reasoning model
- **Tavily** - runtime retrieval of ROS 2 fault-recovery guidance
- **ROS 2 Jazzy** - robotics middleware
- **Gazebo Harmonic** - physics simulation
- **Nav2** - autonomous navigation stack
- **TurtleBot3 Waffle** - simulated rover platform
- **Python** (agent) + **C++** (fault trigger, recovery executor)

<!-- ## Status

| Component | Status |
|---|---|
| Gazebo tunnel world + rover spawn | **OK** - Working |
| ROS 2 to Gazebo bridge (`/scan`, `/odom`, `/cmd_vel`, `/tf`, `/clock`) | **OK** - Verified with `ros2 topic hz` |
| Fault injection node (`atide_fault_trigger`) | **OK** - Built, tested with manual parameter toggle |
| Nav2 autonomous navigation | **OK** - Sequential goals verified end to end |
| Diagnostics agent (`atide_diagnostics_agent`) | **OK** - Full pipeline: Tavily, Nemotron, reasoning trace, vocabulary validation, HALT fallback |
| Diagnostics agent - end-to-end test with faked fault | **OK** - Verified, 13 runs across both severities |
| Recovery executor | Not yet written |
| Hardcoded baseline | Not yet written |
| Integrated demo (agent + executor + baseline + sim) | Not yet assembled |

*Test results: across the verification runs, `intermittent` faults produce a recovery action
(`RETRY_NAVIGATION` or `REVERSE_AND_REPLAN`) in the large majority of cases; `complete` faults produce
`HALT` in the large majority of cases. The one anomalous case was a prompt-format variation (the model
echoed the prompt's line label into its answer) that was caught by the vocabulary validator and safely
downgraded to `HALT`; the prompt template was subsequently tightened to remove the ambiguity, and the
anomaly has not recurred.* -->

## How I used Nemotron

The recovery decision is not a classification task. A classifier, a lookup table, or a set of rules
would be sufficient if the correct response were always the same. It isn't: the right action for an
intermittent fault during a routine corridor traverse is different from the right action for the same
fault during a delicate approach, and different again for a complete dropout that may or may not be
recoverable given the current mission state.

Nemotron is used as a reasoning model, not a classifier. Given the fault severity, the definitions of
each severity level, and retrieved ROS 2 recovery guidance, it produces a decision, a rationale, and a
full chain-of-thought trace that is captured via the `reasoning` field on the response and published to
`/reasoning_trace`. The trace is what makes the decision auditable: you can see the model weigh
`RETRY_NAVIGATION` against `REVERSE_AND_REPLAN` against `HALT`, cite the retrieved Tavily context, and
commit.

**The model's output is validated before it reaches the robot.** If Nemotron returns a string outside
the decision vocabulary, the agent logs the anomaly and fails safe to `HALT`. The LLM *proposes*; a
deterministic layer *validates* before anything reaches the actuators.

## How I used Tavily

Tavily is called at runtime, before every reasoning step, not at build time, not as a static prompt
prefix. The agent constructs a query from the specific fault severity (`intermittent` vs `complete`)
plus the operating context (`ROS 2 Nav2`, `LiDAR`, `autonomous navigation`), retrieves the top three
results, and embeds them into the Nemotron prompt as grounding.

**Why runtime retrieval matters here.** ROS 2 fault-recovery best practices evolve, new QoS patterns,
new Nav2 recovery server configurations, new diagnostic approaches. A static prompt would encode the
model's training-data snapshot from an arbitrary point in the past. Tavily gives the agent *current*
guidance on every decision, and the reasoning trace visibly references what was retrieved. Without the
Tavily call, the prompt has no grounding in current practice; the decision is a guess dressed as a
judgment.

## Architecture

```
                    +------------------+
                    |  Gazebo Harmonic |
                    |  + TurtleBot3    |
                    +--------+---------+
                             |
                    /scan, /odom, /clock
                             |
                             v
                    +------------------+
                    |  ros_gz_bridge   |
                    +--------+---------+
                             |
              +--------------+-----------------+
              |              |                 |
              v              v                 v
    +----------------+    +--------+  +------------------+
    | fault_trigger  |    |  /tf   |  |  Nav2 stack      |
    |                |    |        |  |  (planner,       |
    | /scan          |    +--------+  |   controller,    |
    |   ->           |                |   costmaps)      |
    | /scan_filtered |                +--------+---------+
    | /fault_severity|                       |
    +------+---------+                       | /cmd_vel
             |                               v
             |                       +--------------+
             |                       |  Gazebo      |
             |                       |  diff-drive  |
             |                       +--------------+
             |
             v
      +------------------------------------------+
      |  Diagnostics Agent                       |
      |                                          |
      |   /fault_severity ->                     |
      |     Tavily search ->                     |
      |     Nemotron reasoning ->                |
      |     vocabulary validation ->             |
      |   /recovery_decision                     |
      |   /recovery_rationale                    |
      |   /reasoning_trace                       |
      +------------------+-----------------------+
                         |
                         v
      +------------------------------+
      |  Recovery Executor           |
      |  (cancel / resend Nav2 goal, |
      |   or publish /cmd_vel)       |
      +------------------------------+
```
<!-- 
## Setup

```bash
# Assumes ROS 2 Jazzy + Gazebo Harmonic + Nav2 already installed
git clone https://github.com/gab-lap/A.T.I.D.E.
cd A.T.I.D.E.

# Python dependencies for the diagnostics agent
# Installed to the user site-packages. ROS 2's build system expects the
# system Python, and an isolated venv breaks the shebang chain used by
# colcon build and ros2 run.
pip3 install --user --break-system-packages -r requirements.txt

# Add your Nebius + Tavily API keys
cp .env.example .env
# edit .env with your keys (both free tiers work)

# Build the workspace
colcon build --symlink-install
source install/setup.bash

# Launch the simulation
ros2 launch atide_bringup simulation.launch.py
```

In a second terminal, trigger a fault manually:

```bash
source install/setup.bash
ros2 param set /fault_trigger_node fault_mode intermittent
```

To run the diagnostics agent standalone (without the full simulation):

```bash
ros2 run atide_diagnostics_agent diagnostics_agent_node --ros-args \
  -p env_file:=$(pwd)/.env
```

Watch the agent's terminal. The full reasoning trace, the retrieved context, and the final decision
appear there, and the decision is republished on `/recovery_decision`.

## What's next

- **Recovery Executor** - consumes `/recovery_decision` and translates it into Nav2 goal cancel/resend
  or direct `/cmd_vel` commands. This closes the loop: reasoning that doesn't act is not recovery.
- **Hardcoded baseline** - runs the same fault scenario with a trivial rule (`any fault -> HALT`) so the
  demo can show the two side by side.
- **Concurrency note.** The Diagnostics Agent's Tavily and Nemotron calls run synchronously in the
  subscription callback. This is fine for the current single-subscription design, since nothing else
  competes for the callback thread. A second input (e.g., an operator chat topic) or a heartbeat timer
  would require moving the API calls off the callback thread.
- **Hardware-in-the-loop extension** (post-core) - a physical hexapod executing the same
  `/recovery_decision` vocabulary over its existing wireless link, as physical proof the decision
  vocabulary generalizes beyond the simulated rover. -->

## License

MIT - see [LICENSE](LICENSE).