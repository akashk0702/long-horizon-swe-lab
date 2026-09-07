"""Load bounded YAML without duplicate keys, aliases, or implicit execution."""

from pathlib import Path

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken

from long_horizon_swe.core.exceptions import TaskConfigError
from long_horizon_swe.core.task import TaskSpec

# Task manifests contain contracts, not datasets. Bound parsing memory and recursion.
MAX_MANIFEST_BYTES = 1_048_576
MAX_YAML_DEPTH = 32


def _check_node(node: Node, depth: int = 0) -> None:
    if depth > MAX_YAML_DEPTH:
        raise TaskConfigError(f"manifest nesting exceeds {MAX_YAML_DEPTH} levels")
    if isinstance(node, MappingNode):
        seen: set[str] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
                raise TaskConfigError("manifest mapping keys must be strings")
            if key.value in seen:
                # Do not echo user-provided values, which could contain sensitive input.
                raise TaskConfigError(f"duplicate YAML key at line {key.start_mark.line + 1}")
            seen.add(key.value)
            _check_node(value, depth + 1)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            _check_node(child, depth + 1)


def load_task(path: Path) -> TaskSpec:
    """Parse and validate a task without resolving a workspace or running a command."""
    try:
        with path.open("rb") as manifest:
            raw = manifest.read(MAX_MANIFEST_BYTES + 1)
    except OSError as error:
        raise TaskConfigError(f"cannot read manifest: {error.strerror or 'I/O error'}") from error
    if len(raw) > MAX_MANIFEST_BYTES:
        raise TaskConfigError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    try:
        content = raw.decode("utf-8")
    except UnicodeError as error:
        raise TaskConfigError("manifest must be UTF-8") from error
    try:
        for token in yaml.scan(content, Loader=yaml.SafeLoader):
            if isinstance(token, (AliasToken, AnchorToken)):
                raise TaskConfigError("YAML anchors and aliases are not supported")
        node = yaml.compose(content, Loader=yaml.SafeLoader)
        if not isinstance(node, MappingNode):
            raise TaskConfigError("manifest must contain one YAML mapping")
        _check_node(node)
        data = yaml.safe_load(content)
    except (yaml.YAMLError, RecursionError) as error:
        raise TaskConfigError("invalid YAML; check syntax, nesting, and scalar types") from error
    try:
        return TaskSpec.model_validate(data)
    except ValidationError as error:
        # Field locations and messages are enough; never dump the entire manifest.
        diagnostics = []
        for issue in error.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in issue["loc"]) or "task"
            diagnostics.append(f"{location}: {issue['msg']}")
        raise TaskConfigError("invalid task configuration: " + "; ".join(diagnostics)) from error
