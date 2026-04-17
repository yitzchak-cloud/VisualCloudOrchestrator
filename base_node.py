from dataclasses import dataclass, field
from typing import ClassVar
from port_types import PortType, PORT_META


@dataclass
class Port:
    name:      str
    port_type: PortType
    multi:     bool = False    # output: can fan-out to many targets
    required:  bool = False
    multi_in:  bool = False    # input:  can accept more than one incoming edge


@dataclass
class GCPNode:
    node_id: str
    label:   str

    # subclasses declare these as ClassVar
    inputs:      ClassVar[list[Port]] = []
    outputs:     ClassVar[list[Port]] = []
    node_color:  ClassVar[str]        = "#1e293b"
    icon:        ClassVar[str]        = "box"
    category:    ClassVar[str]        = "General"
    description: ClassVar[str]        = ""

    @classmethod
    def ui_schema(cls) -> dict:
        return {
            "type":        cls.__name__,
            "label":       cls.__name__.replace("Node", "").replace("_", " "),
            "description": cls.description,
            "color":       cls.node_color,
            "icon":        cls.icon,
            "category":    cls.category,
            "inputs": [
                {
                    "name":     p.name,
                    "type":     p.port_type.value,
                    "multi":    p.multi,
                    "multi_in": p.multi_in,
                    "required": p.required,
                    "color":    PORT_META[p.port_type.value]["color"],
                    "label":    PORT_META[p.port_type.value]["label"],
                }
                for p in cls.inputs
            ],
            "outputs": [
                {
                    "name":  p.name,
                    "type":  p.port_type.value,
                    "multi": p.multi,
                    "color": PORT_META[p.port_type.value]["color"],
                    "label": PORT_META[p.port_type.value]["label"],
                }
                for p in cls.outputs
            ],
        }

    def to_yaml_dict(self) -> dict:
        return {
            "type":     self.__class__.__name__,
            "node_id":  self.node_id,
            "label":    self.label,
            "category": self.__class__.category,
        }