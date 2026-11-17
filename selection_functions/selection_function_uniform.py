"""
Functions used to select one option from a set of possible candidates. This is completely de-coupled from the
engine, so the end-user can swap out selection logic (e.g. weighted/biased selection) without touching main.py.
"""

import numpy as np

# Select uniformly at random
def select_action(possible_actions: list):
    """
    Parameters:
        - possible_actions (list): names of all actions that are currently possible to carry out.
    Returns:
        - the selected action name, chosen uniformly at random from possible_actions.
    """
    return np.random.choice(possible_actions)

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
