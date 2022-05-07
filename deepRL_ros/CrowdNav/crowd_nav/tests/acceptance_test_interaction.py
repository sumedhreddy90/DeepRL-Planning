import logging
import argparse
import configparser
import os
import torch
import numpy as np
import gym
import matplotlib.pyplot as plt

from crowd_nav.utils.explorer import Explorer
from crowd_nav.policy.policy_factory import policy_factory
from crowd_sim.envs.utils.robot import Robot
from crowd_sim.envs.utils.human import Human
from crowd_sim.envs.policy.orca import ORCA
from crowd_sim.envs.visualization.observer_subscriber import notify
from crowd_sim.envs.visualization.plotter import Plotter
from crowd_sim.envs.visualization.video import Video


def main():
    parser = argparse.ArgumentParser('Parse configuration file')
    parser.add_argument('--env_config', type=str, default='data/output/env.config')
    parser.add_argument('--policy_config', type=str, default='data/output/policy.config')
    parser.add_argument('--policy', type=str, default='scr')
    parser.add_argument('--model_dir', type=str, default=None)
    parser.add_argument('--il', default=False, action='store_true')
    parser.add_argument('--gpu', default=False, action='store_true')
    parser.add_argument('--visualize', default=False, action='store_true')
    parser.add_argument('--phase', type=str, default='test')
    parser.add_argument('--test_case', type=int, default=None)
    parser.add_argument('--square', default=False, action='store_true')
    parser.add_argument('--circle', default=False, action='store_true')
    parser.add_argument('--video_file', type=str, default=None)
    parser.add_argument('--plot_file', type=str, default=None)
    args = parser.parse_args()

    if args.model_dir is not None:
        env_config_file = os.path.join(args.model_dir, os.path.basename(args.env_config))
        policy_config_file = os.path.join(args.model_dir, os.path.basename(args.policy_config))
        if args.il:
            model_weights = os.path.join(args.model_dir, 'il_model.pth')
        else:
            if os.path.exists(os.path.join(args.model_dir, 'resumed_rl_model.pth')):
                model_weights = os.path.join(args.model_dir, 'resumed_rl_model.pth')
            else:
                model_weights = os.path.join(args.model_dir, 'rl_model.pth')
    else:
        policy_config_file = args.env_config

    # configure logging and device
    logging.basicConfig(level=logging.INFO, format='%(asctime)s, %(levelname)s: %(message)s',
                        datefmt="%Y-%m-%d %H:%M:%S")
    device = torch.device("cuda:0" if torch.cuda.is_available() and args.gpu else "cpu")
    logging.info('Using device: %s', device)

    # configure policy
    policy = policy_factory[args.policy]()
    policy_config = configparser.RawConfigParser()
    policy_config.read(policy_config_file)
    policy.configure(policy_config)
    if policy.trainable:
        if args.model_dir is None:
            parser.error('Trainable policy must be specified with a model weights directory')
        policy.get_model().load_state_dict(torch.load(model_weights))

    # configure environment
    env = gym.make('CrowdSim-v0')
    env.configure(args.env_config)

    robot = Robot()
    robot.configure(args.env_config, 'robot')
    robot.set_policy(policy)
    env.set_robot(robot)

    env.human_num = 1
    humans = [Human() for _ in range(env.human_num)]
    for i, human in enumerate(humans):
        human.configure(args.env_config, 'humans')
    interactive = policy_factory['interactive']()
    humans[0].set_policy(interactive)
    env.set_humans(humans)

    if args.square:
        env.test_sim = 'square_crossing'
    if args.circle:
        env.test_sim = 'circle_crossing'

    policy.set_phase(args.phase)
    policy.set_device(device)
    # set safety space for ORCA in non-cooperative simulation
    if isinstance(robot.policy, ORCA):
        robot.policy.safety_space = 0
        logging.info('ORCA agent buffer: %f', robot.policy.safety_space)

    policy.set_env(env)
    robot.print_info()

    ob = env.reset(args.phase, args.test_case)
    env.set_interactive_human()
    last_pos = np.array(robot.get_position())
    observation_subscribers = []

    if args.plot_file:
        plotter = Plotter(args.plot_file)
        observation_subscribers.append(plotter)
    if args.video_file:
        video = Video(args.video_file)
        observation_subscribers.append(video)
    t = 0
    while not env.humans[0].reached_destination():
        action = robot.act(ob)
        ob, _, done, info = env.step(action)

        notify(observation_subscribers, env.state)
        if args.visualize:
            env.render()

        current_pos = np.array(robot.get_position())
        logging.debug('Speed: %.2f', np.linalg.norm(current_pos - last_pos) / robot.time_step)
        last_pos = current_pos
        t += 1
        if t == 100:
            break

    if args.plot_file:
        plotter.save()
    if args.video_file:
        video.make()

    logging.info('It takes %.2f seconds to finish. Final status is %s', env.global_time, info)
    if robot.visible and info == 'reach goal':
        human_times = env.get_human_times()
        logging.info('Average time for humans to reach goal: %.2f', sum(human_times) / len(human_times))


if __name__ == '__main__':
    main()
