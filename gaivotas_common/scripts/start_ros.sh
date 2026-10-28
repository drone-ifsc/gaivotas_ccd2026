#!/bin/bash
SESSION="ros"

tmux new-session -d -s $SESSION

# Split into 4 equal panes (2x2 grid)
tmux split-window -h -t $SESSION
tmux split-window -v -t $SESSION.0
tmux split-window -v -t $SESSION.2
tmux select-layout -t $SESSION tiled

# Pane 0 (top-left): start container
tmux send-keys -t $SESSION.0 'docker start ros-container & htop' C-m

tmux send-keys -t $SESSION.1 'sleep 2 && docker exec -it ros-container bash -c "rosrun gaivotas_common camera_driver.py"' C-m

tmux send-keys -t $SESSION.2 'sleep 2 && docker exec -it ros-container bash -c "cd /root/catkin_ws/src/ && bash"' C-m

tmux send-keys -t $SESSION.3 'sleep 1 && docker exec -it ros-container bash -c "roscore"' C-m

tmux attach -t $SESSION
