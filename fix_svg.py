import re

with open('assets/lens_logo_high_precision.svg', 'r') as f:
    content = f.read()

# Insert the rect right after the <svg ...> tag
svg_start_idx = content.find('<svg')
svg_end_idx = content.find('>', svg_start_idx) + 1
while content[svg_end_idx] == '\n':
    svg_end_idx += 1

new_content = content[:svg_end_idx] + '  <rect x="0" y="0" width="2048" height="2048" fill="#ffffff"/>\n' + content[svg_end_idx:]

with open('assets/lens_logo_high_precision_with_bg.svg', 'w') as f:
    f.write(new_content)

for readme_file in ['README.md', 'README_CN.md']:
    with open(readme_file, 'r') as f:
        readme_content = f.read()
    
    # Ensure the first logo is lens_logo_high_precision_with_bg.svg
    updated_content = re.sub(
        r'<img src="assets/lens_logo[^"]*"', 
        r'<img src="assets/lens_logo_high_precision_with_bg.svg"', 
        readme_content, 
        count=1
    )
    
    with open(readme_file, 'w') as f:
        f.write(updated_content)

