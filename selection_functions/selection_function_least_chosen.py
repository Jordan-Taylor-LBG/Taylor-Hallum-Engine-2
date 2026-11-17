"""
Functions used to select one option from a set of possible candidates. This is completely de-coupled from the
engine, so the end-user can swap out selection logic (e.g. weighted/biased selection) without touching main.py.

select_action here tracks how many times each action name has been chosen (for the lifetime of this module's
import, i.e. one simulation run) and always picks from whichever action(s) have been chosen the fewest times
so far, so that action usage stays as even as possible over a run.
"""

import numpy as np

_action_selection_counts: dict = {}


def select_action(possible_actions: list):
    """
    Parameters:
        - possible_actions (list): names of all actions that are currently possible to carry out.
    Returns:
        - whichever action in possible_actions has been selected the fewest times so far (ties broken
          uniformly at random). Increments that action's selection count before returning it.
    """
    counts = [_action_selection_counts.get(action, 0) for action in possible_actions]
    min_count = min(counts)
    least_chosen_actions = [action for action, count in zip(possible_actions, counts) if count == min_count]
    selected_action = np.random.choice(least_chosen_actions)
    _action_selection_counts[selected_action] = _action_selection_counts.get(selected_action, 0) + 1
    return selected_action

# Select uniformly at random
def select_entity(possible_entities: list):
    """
    Parameters:
        - possible_entities (list): eligible primary key value combinations to select from, each a tuple of
          (key, value) pairs, e.g. [(('pk', '1'),), (('pk', '2'),)]
    Returns:
        - the selected primary key value combination, chosen uniformly at random from possible_entities.
    """
    idx = np.random.randint(len(possible_entities))
    return possible_entities[idx]
