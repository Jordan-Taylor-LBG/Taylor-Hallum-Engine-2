# Builds dag, configured to work for both table and atribute. Default edge_key is "depends_on", so DAG will have x -> y => x depends on y
def build_dag(objects, name_key: str = "name", edge_key: str = "depends_on"):
    dag = {}
    
    if isinstance(objects,list):
        objects_list = objects
    else:
        # objects is dicionary {"enity_name": {"fields": ..., "depends_on": bool}}
        objects_list = [{"name": k, **v} for k, v in objects.items()]

    for object in objects_list:
        dag[object[name_key]] = []
        try:
            if isinstance(object[edge_key],str):
                # Add to existing list of fields it depends on
                dag[object[name_key]].append(object[edge_key])

            if isinstance(object[edge_key],list):
                # Add to existing list of fields it depends on
                dag[object[name_key]] += object[edge_key]

            else:
                # Format mismatch: neither list nor string
                pass
        except:
            # Attribute is not dependent (no depends_on field)
            pass
    return dag

# Inverts all edges x -> y => y -> x
def invert_dag(dag: dict):
    inverted = {node: [] for node in dag}

    for node, deps in dag.items():
        for dep in deps:
            inverted.setdefault(dep, []).append(node)

    return inverted

# Inverts all edges x -> y => y -> x
def invert_dict(dic: dict):
    return {dic[key]: key for key in dic}

# Checks if directed graph is a DAG (i.e. has no cycles)
def is_dag(graph):
    """
    graph: dict[str, list[str]]

    Returns True if graph is a DAG, else False.
    """

    state = {}  # 0=unvisited, 1=visiting, 2=visited

    # Depth First Search
    def dfs_helper(node):
        if state.get(node, 0) == 1:
            return False  # cycle found

        if state.get(node, 0) == 2:
            return True   # already processed

        state[node] = 1

        for neighbour in graph.get(node, []):
            if not dfs_helper(neighbour):
                return False

        state[node] = 2
        return True

    # Include nodes that only appear as dependencies
    all_nodes = set(graph)
    for deps in graph.values():
        all_nodes.update(deps)

    return all(dfs_helper(node) for node in all_nodes if state.get(node, 0) == 0)

# Gives list of nodes s.t. x preceeds y => x is a parent of y
def topological_sort(graph: dict):
    visited = set()
    order = []

    def dfs(node):
        if node in visited:
            return

        visited.add(node)

        for dependent in graph.get(node, []):
            dfs(dependent)

        order.append(node)

    # Include nodes that only appear as dependents
    all_nodes = set(graph)
    for dependents in graph.values():
        all_nodes.update(dependents)

    for node in all_nodes:
        dfs(node)

    return order[::-1]

# Finds roots of DAG (works in both cases if keys is complete set of nodes or not - e.g. 'b':[] or 'b' not included)
def get_roots_of_dag(dag: dict):
    indegree = {node: 0 for node in dag}

    # Calculate indegrees
    for node in dag:
        for neighbor in dag[node]:
            if neighbor not in indegree:
                indegree[neighbor] = 0
            indegree[neighbor] += 1

    # Roots have no incoming edges
    return [node for node, degree in indegree.items() if degree == 0]

# Find leaves of DAG, only works if keys of DAG is complete list of nodes (more efficient than get_roots_of_dag O(n) vs O(n^2))
def get_leaves_of_dag(dag: dict):
    leaves = []
    for node in dag:
        if dag[node] == []:
            leaves.append(node)

    return leaves

# Given a graph and a subset of nodes, returns a graph with information only on subset of nodes provided
def get_sub_graph(graph: dict, nodes_subset: list):
    sub_graph = {}
    for node in graph:
        if  node in nodes_subset:
            sub_graph[node] = list(set(graph[node]) & set(nodes_subset))

    return sub_graph

# Gets a subset of the key value pairs from a tuple, given a tuple of keys
def get_subset_key_value_pairs(key_value_pairs: tuple, keys: tuple):
    return tuple((key, value,) for key, value in key_value_pairs if key in keys)

import random
import string
import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal

# Used to generate attribute where no default function is given: Generates a random value for a given datatype
def generate_random_value_of_given_type(datatype: str):
    """
    Generate a random value for the supplied datatype.

    Supported datatypes:
        str, string
        int, integer
        float
        decimal
        bool, boolean
        date
        datetime, timestamp
        uuid
        list
    """

    datatype = datatype.lower()

    generators = {
        "str": lambda: "".join(random.choices(string.ascii_letters + string.digits, k=10)),
        "string": lambda: "".join(random.choices(string.ascii_letters + string.digits, k=10)),
        "int": lambda: random.randint(0, 1_000_000),
        "integer": lambda: random.randint(0, 1_000_000),
        "float": lambda: random.uniform(0, 1_000_000),
        "decimal": lambda: Decimal(f"{random.uniform(0, 1_000_000):.2f}"),
        "bool": lambda: random.choice([True, False]),
        "boolean": lambda: random.choice([True, False]),
        "date": lambda: date.today() + timedelta(days=random.randint(-3650, 3650)),
        "datetime": lambda: datetime.now() + timedelta(
            seconds=random.randint(-315360000, 315360000)
        ),
        "timestamp": lambda: datetime.now() + timedelta(
            seconds=random.randint(-315360000, 315360000)
        ),
        "uuid": lambda: str(uuid.uuid4()),
        "list": lambda: [random.randint(0, 100) for _ in range(random.randint(1, 10))],
    }

    try:
        return generators[datatype]()
    except KeyError:
        raise ValueError(f"Unsupported datatype: {datatype}")