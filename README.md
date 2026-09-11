# A.T.I.D.E. — Diagnostics Agent

A diagnostics subsystem for autonomous rovers operating in degraded environments. Built for the [Nebius x NVIDIA Global AI Hackathon](https://nebiusglobalaihackathon.devpost.com/) (Physical AI Track).

## What this is

A ROS 2 / Gazebo pipeline that detects LiDAR faults on a simulated rover, retrieves relevant recovery knowledge via Tavily, and uses NVIDIA Nemotron 3 Nano (on Nebius Token Factory) to reason through a decision: retry navigation, reverse and re-plan, or halt.

The agent surfaces its reasoning trace live, so the decision is explainable rather than opaque.

## Status

Under active development. Full documentation and setup instructions will be added before submission.

## License

MIT — see [LICENSE](LICENSE).
