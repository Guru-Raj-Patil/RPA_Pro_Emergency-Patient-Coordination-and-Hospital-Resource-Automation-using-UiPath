import os
import re
import glob

root = r'c:\Users\Gurupatil\Documents\UiPath\Emergency Patient Coordination and Hospital Resource Automation using UiPath'
xaml_files = glob.glob(os.path.join(root, '**', '*.xaml'), recursive=True)

# 1. Merge Input/Output Arguments when both exist
re_code_both = re.compile(r'<ui:InvokeCode\.InputArguments>(.*?)</ui:InvokeCode\.InputArguments>\s*<ui:InvokeCode\.OutputArguments>(.*?)</ui:InvokeCode\.OutputArguments>', re.DOTALL)
re_wf_both = re.compile(r'<ui:InvokeWorkflowFile\.InputArguments>(.*?)</ui:InvokeWorkflowFile\.InputArguments>\s*<ui:InvokeWorkflowFile\.OutputArguments>(.*?)</ui:InvokeWorkflowFile\.OutputArguments>', re.DOTALL)

# 2. Convert remaining InputArguments to Arguments
re_code_in = re.compile(r'<ui:InvokeCode\.InputArguments>(.*?)</ui:InvokeCode\.InputArguments>', re.DOTALL)
re_wf_in = re.compile(r'<ui:InvokeWorkflowFile\.InputArguments>(.*?)</ui:InvokeWorkflowFile\.InputArguments>', re.DOTALL)

# 3. Convert remaining OutputArguments to Arguments (if any)
re_code_out = re.compile(r'<ui:InvokeCode\.OutputArguments>(.*?)</ui:InvokeCode\.OutputArguments>', re.DOTALL)
re_wf_out = re.compile(r'<ui:InvokeWorkflowFile\.OutputArguments>(.*?)</ui:InvokeWorkflowFile\.OutputArguments>', re.DOTALL)

for file in xaml_files:
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()

    orig = content

    # Fix ArgumentName to x:Key
    content = content.replace('ArgumentName=', 'x:Key=')

    # Merge Both
    content = re_code_both.sub(r'<ui:InvokeCode.Arguments>\1\2</ui:InvokeCode.Arguments>', content)
    content = re_wf_both.sub(r'<ui:InvokeWorkflowFile.Arguments>\1\2</ui:InvokeWorkflowFile.Arguments>', content)

    # Convert isolated InputArguments
    content = re_code_in.sub(r'<ui:InvokeCode.Arguments>\1</ui:InvokeCode.Arguments>', content)
    content = re_wf_in.sub(r'<ui:InvokeWorkflowFile.Arguments>\1</ui:InvokeWorkflowFile.Arguments>', content)

    # Convert isolated OutputArguments
    content = re_code_out.sub(r'<ui:InvokeCode.Arguments>\1</ui:InvokeCode.Arguments>', content)
    content = re_wf_out.sub(r'<ui:InvokeWorkflowFile.Arguments>\1</ui:InvokeWorkflowFile.Arguments>', content)

    if orig != content:
        with open(file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Updated {os.path.basename(file)}')

print('Done fixing arguments.')
