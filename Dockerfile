# A.T.I.D.E. agent-only image: diagnostics agent + hardcoded baseline, no simulator, no GPU.
# Build context: the repository root (the folder that contains atide_diagnostics_agent/).
FROM ros:jazzy-ros-base

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ws

# Python dependencies first so Docker caches this layer.
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --break-system-packages -r /tmp/requirements.txt

# Copy the repo into the workspace and build only the diagnostics agent package
# (plus any workspace package it depends on).
COPY . /ws/src/A.T.I.D.E.
RUN . /opt/ros/jazzy/setup.sh \
    && colcon build --packages-up-to atide_diagnostics_agent

COPY docker/demo.sh /demo.sh
RUN chmod +x /demo.sh \
    && printf '#!/bin/bash\nset -e\nsource /opt/ros/jazzy/setup.bash\nsource /ws/install/setup.bash\nexec "$@"\n' > /entrypoint.sh \
    && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/demo.sh"]
