# A.T.I.D.E. - Autonomous & Teleoperated Intervention in Degraded Environments

An agent runtime for autonomous rover fault recovery: a ROS 2 / Gazebo navigation pipeline that detects
sensor faults live, reasons about the best recovery action using retrieval-augmented LLM reasoning, and
acts on that decision, with the reasoning itself surfaced, not hidden.

Built for the [Nebius x NVIDIA Global AI Hackathon](https://nebiusglobalaihackathon.devpost.com/)
(Physical AI Track).


**Demo video:** [YouTube link](https://www.youtube.com/watch?v=...)

## The problem

Autonomous inspection and survey rovers operate in environments where sensor faults are expected, not
exceptional, like tunnels, collapsed structures, planetary caves. When a LiDAR drops out, a conventional
rule-based system does the safest thing it knows: halt. That's correct behavior *if the fault is
unrecoverable*. But it's the wrong response to an intermittent glitch, and it's the wrong response to a
fault whose cause is a misconfiguration rather than hardware failure.

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
- **Docker** - containerized agent demo and evaluation harness
- **Python** (agent) + **C++** (fault trigger, recovery executor)

## Status

| Component | Status |
|---|---|
| Gazebo tunnel world + rover spawn | **OK** - Working |
| ROS 2 to Gazebo bridge (`/scan`, `/odom`, `/cmd_vel`, `/tf`, `/clock`) | **OK** - Verified with `ros2 topic hz` |
| Fault injection node (`atide_fault_trigger`) | **OK** - Modes `none`, `intermittent`, `complete`, set live with `ros2 param set` |
| Nav2 autonomous navigation | **OK** - Sequential goals verified end to end |
| Diagnostics agent (`atide_diagnostics_agent`) | **OK** - Tavily retrieval, Nemotron reasoning, reasoning trace, vocabulary validation, HALT fallback |
| Recovery executor (`atide_recovery_executor`) | **OK** - `HALT`, `RETRY_NAVIGATION` and `REVERSE_AND_REPLAN` verified end to end in simulation |
| Hardcoded baseline (`baseline_agent_node`) | **OK** - any fault -> `HALT`, publishes to `/baseline_decision`; side-by-side test passed |
| Containerized agent demo (no simulator) | **OK** - `docker compose up` exits 0, both nodes print side by side |
| Containerized evaluation harness (`docker/eval_harness.py`) | **OK** - 30 runs per severity, table in [Evaluation](#evaluation) |
| Single-command launch of the full stack | Not yet - runs as separate terminals (see Run) |

*Test results, in short: on `intermittent` faults the agent chose a recovery action in 30 of 30 runs
(26 `REVERSE_AND_REPLAN`, 4 `RETRY_NAVIGATION`) and did not `HALT` in any of them; on `complete` faults it chose `HALT` in
30 of 30. The hardcoded baseline answers `HALT` to every fault by construction. Details and limits are in
[Evaluation](#evaluation).*

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

## How I used Nebius Token Factory

Every reasoning call goes to Nemotron 3 Nano served by Nebius Token Factory, through the `openai` Python
client pointed at the Token Factory endpoint. No model runs locally: the agent container is CPU-only and
the 30B-parameter model lives behind the endpoint, which is what lets the whole decision layer run from a
plain `docker compose up` on a laptop with no GPU. In the 30-run evaluation (60 calls) every injection produced a decision, with no timeouts, and the
median time from fault to decision was 5.7 s for intermittent and 4.4 s for complete faults, including
the Tavily search. The reasoning trace comes back in the response's `reasoning` field (not `reasoning_content`),
which the agent reads and publishes.

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
           |                                 v
           |                         +--------------+
           |                         |  Gazebo      |
           |                         |  diff-drive  |
           |                         +--------------+
           |
           +----------------------------------------------+
           |                                              |
           v                                              v
  +------------------------------------------+   +--------------------------------------+
  |  Diagnostics Agent                       |   |  Hardcoded baseline                  |
  |                                          |   |                                      |
  |   /fault_severity ->                     |   |   /fault_severity ->                 |
  |     Tavily search ->                     |   |     /baseline_decision               |
  |     Nemotron reasoning ->                |   |   any fault -> HALT                  |
  |     vocabulary validation ->             |   |   (comparison only, not wired to the |
  |   /recovery_decision                     |   |    recovery executor)                |
  |   /recovery_rationale                    |   |                                      |
  |   /reasoning_trace                       |   |                                      |
  +------------------+-----------------------+   +--------------------------------------+
                     |
                     v
  +------------------------------------+
  |  Recovery Executor                 |
  |  (cancel / resend the Nav2 goal,   |
  |   or back up through Nav2's        |
  |   behavior_server, then re-send)   |
  +------------------------------------+
```

## Repository layout

```
atide_bringup/              launch files, config, Gazebo tunnel world (no compiled code)
atide_fault_trigger/        C++ - degrades /scan into /scan_filtered, publishes /fault_severity
atide_diagnostics_agent/    Python - diagnostics agent (Tavily + Nemotron) and the hardcoded baseline
atide_recovery_executor/    C++ - acts on /recovery_decision through Nav2
docker/                     demo.sh, eval.sh, eval_harness.py - the containerized demo and evaluation
Dockerfile, docker-compose.yml
```

## Setup

There are two ways to run A.T.I.D.E.

- **Full simulation** (Gazebo + Nav2 + the whole pipeline): native install, described below. This is what
  the demo video shows.
- **Agent demo, no simulator** (Tavily + Nemotron + baseline, in one container): see
  [Quick demo with Docker](#quick-demo-with-docker). Fastest way to see the reasoning for yourself.

### Requirements

- Ubuntu 24.04 with ROS 2 Jazzy, Gazebo Harmonic and Nav2 installed
- A Nebius Token Factory API key and a Tavily API key (both have free tiers)

### Build

```bash
mkdir -p ~/atide_ws/src && cd ~/atide_ws/src
git clone https://github.com/gab-lap/A.T.I.D.E.
cd A.T.I.D.E.

# Python dependencies for the diagnostics agent.
# Installed to the user site-packages: ROS 2's build tools expect the system Python, and an isolated
# venv breaks the shebang chain used by colcon build and ros2 run.
pip3 install --user --break-system-packages -r requirements.txt

# Add your API keys
cp .env.example .env
# edit .env with your Nebius and Tavily keys

# Install ROS dependencies declared in the package.xml files, then build
cd ~/atide_ws
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

### Run

Use one terminal per line. In every terminal, run `source ~/atide_ws/install/setup.bash` first.

```bash
# 1. Simulation + Nav2
ros2 launch atide_bringup simulation.launch.py

# 2. Recovery executor
ros2 run atide_recovery_executor recovery_executor_node --ros-args -p use_sim_time:=true

# 3. Diagnostics agent (the explicit env_file path matters, see note below)
ros2 run atide_diagnostics_agent diagnostics_agent_node --ros-args \
  -p env_file:=$HOME/atide_ws/src/A.T.I.D.E./.env

# 4. Hardcoded baseline (comparison only, the executor ignores it)
ros2 run atide_diagnostics_agent baseline_agent_node

# 5. Inject a fault while the rover is driving
ros2 param set /fault_trigger_node fault_mode intermittent   # or: complete, none
```

Watch terminal 3. The retrieved Tavily context, the Nemotron reasoning trace and the final decision
appear there, and the decision is republished on `/recovery_decision`. Terminal 4 shows what the
hardcoded rule would have done instead.

**Why `env_file` is passed explicitly.** After `colcon build`, the executed file lives under `build/`,
which is a sibling of `src/`, not a parent. `load_dotenv()` searches upward from the executed file and
never reaches the `.env` in the repository.

**If the terminal fills with `Detected jump back in time`:** an orphan `ros_gz_bridge` from a previous
run is publishing a second `/clock`. Kill leftovers before relaunching:

```bash
pkill -9 -f "gz sim"; pkill -9 -f ros_gz_bridge; pkill -9 -f rviz2; pkill -9 -f component_container
```

## Quick demo with Docker

No simulator, no GPU, no ROS installation needed, only Docker and your API keys. The container runs the
diagnostics agent and the baseline together, injects an `intermittent` and then a `complete` fault, and
prints both nodes' output in one terminal: the baseline answers `HALT` instantly, the agent searches,
reasons, and then decides.

```bash
git clone https://github.com/gab-lap/A.T.I.D.E.
cd A.T.I.D.E.
cp .env.example .env      # add your Nebius and Tavily keys
docker compose up --build
```

It takes about a minute and a half and makes two Tavily searches and two Nemotron calls with your keys.
The agent's decision for the intermittent fault can differ from run to run (see Evaluation).

The recovery executor and Nav2 are not part of this container: it demonstrates the decision layer only.
The full closed loop (decision -> executor -> rover) is the native setup above.

## Evaluation

`docker/eval_harness.py` injects each severity N times, waits for `/recovery_decision` with a timeout,
and tabulates decisions and latency. It depends only on `/fault_severity` and `/recovery_decision`, not
on the agent's internals. Run it against the container:

```bash
docker compose run --rm -e RUNS=30 demo bash /ws/src/A.T.I.D.E./docker/eval.sh
```

Results from one run of 30 injections per severity, CPU-only container, Nemotron 3 Nano on Nebius Token
Factory (raw output in [`docs/eval_run.log`](docs/eval_run.log)):

| severity | runs | HALT | RETRY_NAVIGATION | REVERSE_AND_REPLAN | median latency (s) |
|---|---|---|---|---|---|
| intermittent | 30 | 0 | 4 | 26 | 5.7 |
| complete | 30 | 30 | 0 | 0 | 4.4 |

The hardcoded baseline is a one-line rule (any fault -> `HALT`), so it answers `HALT` to every fault by
construction. The harness measures the agent only.

**How to read it.** The behaviour I tested against is my own design choice, not ground truth: for
`intermittent` faults any recovery action counts as the intended outcome, for `complete` faults `HALT`
does. On that reading:

- **Complete failure:** the agent halted in 30 of 30 runs, the same as the baseline. With no sensor data
  at all, halting is the right answer, so this is agreement, not an advantage.
- **Intermittent fault:** the agent chose a recovery action in 30 of 30 runs and did not halt in any of them, where the
  baseline halts on every one of these faults. This is the difference the project is about. An earlier
  10-run sample on the same setup produced two `HALT`s and eight `REVERSE_AND_REPLAN`, so the rate of
  `HALT` on intermittent faults is low, but I would not call it zero.
- **Which recovery:** 26 of 30 were `REVERSE_AND_REPLAN` and 4 were `RETRY_NAVIGATION`. The model mostly
  picks the heavier recovery over the cheapest one, and its choice between the two is not stable.
- **Latency:** the median time from fault injected to decision was 5.7 s for intermittent faults and 4.4 s
  for complete ones. That includes the Tavily search and the Nemotron call.

**Limits.** Thirty runs per severity, on a single day, is still a small sample; there are no confidence
intervals. The harness cannot tell a validator fallback (`HALT` because the model returned something
outside the vocabulary) from a genuine `HALT`, because both arrive on the same topic, so some of the 30
`HALT`s on complete faults could be fallbacks; the outcome is the same either way.

## What's next

- **Evaluation at scale on Nebius Serverless Jobs.** The image, the harness and the environment-variable
  interface are built so the same evaluation can run as a batch job. I have only run it locally in the
  container, not on Nebius; a run there would add to the local 30-run sample.
- **Full-simulation container.** Gazebo, Nav2 and the pipeline in one image, run headless with a browser
  desktop for RViz, so the whole closed loop needs only Docker.
- **Single launch file** for simulation, executor, agent and baseline.
- **Concurrency note.** The diagnostics agent's Tavily and Nemotron calls run synchronously in the
  subscription callback. This is fine for the current single-subscription design, since nothing else
  competes for the callback thread. A second input (for example an operator chat topic) or a heartbeat
  timer would require moving the API calls off the callback thread.
- **Hardware-in-the-loop extension** - a physical hexapod executing the same `/recovery_decision`
  vocabulary over its existing wireless link, as physical proof that the decision vocabulary generalizes
  beyond the simulated rover.

## License

MIT - see [LICENSE](LICENSE).
