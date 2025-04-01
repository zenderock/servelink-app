COLORS = [
    'blue',
    'indigo',
    'violet',
    'purple',
    'fuchsia',
    'pink',
    'rose',
    'red',
    'orange',
    'amber',
    'yellow',
    'lime',
    'green',
    'emerald',
    'teal',
    'cyan',
    'sky',
]

def get_project_color(id: str) -> str:
    """Get a deterministic color based on the project ID."""
    color_index = sum(ord(c) for c in str(id)) % len(COLORS)
    return COLORS[color_index]