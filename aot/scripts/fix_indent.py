"""Fix over-indentation in the ISRIC layer block of ai_context_service.py."""
import sys

with open('aot/services/ai_context_service.py', 'r') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    # From line 898 to 976 (0-indexed: 897 to 975) we need to remove 4 spaces
    # Let's just find the start of the comment "# Find which ISRIC layers"
    if "Find which ISRIC layers are active by string matching" in line:
        start_idx = i
        break

for i in range(len(lines)):
    if start_idx <= i <= start_idx + 80:
        if lines[i].startswith("                            "): # 28 spaces
            # Remove 4 spaces
            new_lines.append(lines[i][4:])
        elif lines[i].startswith("                                "): 
            new_lines.append(lines[i][4:])
        elif lines[i].strip() == "":
            new_lines.append(lines[i])
        else:
            # Maybe already dedented?
            new_lines.append(lines[i])
    else:
        new_lines.append(lines[i])

with open('aot/services/ai_context_service.py', 'w') as f:
    f.writelines(new_lines)

print("Indentation fixed.")
