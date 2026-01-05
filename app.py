import os
from dotenv import load_dotenv
from openai import OpenAI
import json
import streamlit as st
import re

#--- STREAMLIT CONFIG ---
st.set_page_config(layout="wide")

# --- SAFE UI RESET ---
if st.session_state.get("pending_clear_notes"):
    st.session_state.user_input_key = ""
    st.session_state.pending_clear_notes = False

# --- ARCHIVE LOGIC ---
def close_archive():
    """Explicitly closes the recently deleted expander."""
    st.session_state.archive_open = False
def open_archive():
    """Explicitly opens the recently deleted expander."""
    st.session_state.archive_open = True


# --- INITIALIZE ---
if "archive_open" not in st.session_state:
    st.session_state.archive_open = False
if "trash_archive" not in st.session_state:
    st.session_state.trash_archive = []
if "analysis_ready" not in st.session_state:
    st.session_state.analysis_ready = False

# --- API CLIENT SETUP ---
client=OpenAI(
        base_url="http://localhost:11434/v1",
        api_key="ollama"
        )

# --- PERMANENT STORAGE HELPERS ---
HISTORY_FILE = "history_log.json"

def load_history():
    """Opens the 'filing cabinet' and returns all saved analyses."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

def parse_tasks(text):
    """Clean the AI response and convert the JSON list into checkboxes."""
    try:
        # 1. Search for a pattern starting with [ and ending with ]
        # This ignores any extra text or Markdown tags like ```json
        match = re.search(r'\[.*\]', text, re.DOTALL)
        
        if match:
            # 2. Extract only the bracketed part
            clean_json = match.group(0)
            task_names = json.loads(clean_json)
            # 3. Create the list of task dictionaries
            return [{"task": name, "done": False} for name in task_names]
        
        # If no brackets are found, trigger the fallback
        raise ValueError("No JSON list found")
        
    except Exception:
        # Fallback: Treat the whole block as one task if parsing fails
        return [{"task": text.strip(), "done": False}]

def save_to_history(project_name, reasoning, plan_text):
    history = load_history()
    new_entry = {
        "project": project_name,
        "reasoning": reasoning.strip(),
        "tasks": parse_tasks(plan_text) # Process the text here!
    }
    history.insert(0, new_entry) # Put newest at the top
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

# Find the project we are looking for
def update_task_status(history_data, project_name, task_index, new_status):
    for item in history_data:
        if item["project"] == project_name:
            item["tasks"][task_index]["done"] = new_status
            break
    with open(HISTORY_FILE, "w") as f:
        json.dump(history_data, f, indent=4)

def delete_from_history(history_data, project_name):
    deleted_item = None
    new_history = []
    
    for item in history_data:
        # If we find the project and haven't 'deleted' one yet
        if item["project"] == project_name and deleted_item is None:
            deleted_item = item
            # We don't add this one to new_history
        else:
            # Keep all other items
            new_history.append(item)
    
    # Only write to the file if we actually removed something
    if deleted_item:
        with open(HISTORY_FILE, "w") as f:
            json.dump(new_history, f, indent=4)
            
    return deleted_item

@st.dialog("Create New Project 📁")
def new_project_dialog(should_trigger=False):
    # Using a form allows "Enter" to trigger the submit button
    with st.form("new_project_form", clear_on_submit=True):
        st.write("What would you like to call this project?")
        new_name = st.text_input("Project Name", placeholder="e.g., Client - Job Name")
        
        # This button handles both the click and the "Enter" keypress
        submitted = st.form_submit_button("Confirm ✅", use_container_width=True)
        
        if submitted:
            if new_name:
                history = load_history()
                final_name = get_unique_name(all_history, new_name)
                st.session_state.current_project_name = final_name

                if should_trigger:
                    st.session_state.analysis_ready = True

                # Cleanup We keep the user_input_area so notes aren't lost!
                if "selected_analysis" in st.session_state:
                    del st.session_state.selected_analysis
            
                st.rerun()
            else:
                st.error("Please enter a name.")

@st.dialog("Rename Project ✏️")
def rename_dialog(old_name, all_history):
    with st.form("rename_project_form"):
        st.write(f"Enter a new name for **{old_name}**:")
        new_name = st.text_input("New Project Name", value=old_name)
        
        submitted = st.form_submit_button("Save Changes ✅", use_container_width=True)
        
        if submitted:
            if new_name and new_name != old_name:
                rename_project_in_history(all_history, old_name, new_name)
                # If the renamed project was the one currently being viewed, update the view
                if st.session_state.get("selected_analysis", {}).get("project") == old_name:
                    st.session_state.selected_analysis["project"] = new_name
            st.rerun()

# name uniqueness checker
def get_unique_name(existing_history, target_name):
    # Checks if a name exists and adds (1), (2), etc. if needed.
    existing_names = [item["project"] for item in existing_history]
    if target_name not in existing_names:
        return target_name
    
    counter = 1
    new_name = f"{target_name} ({counter})"
    while new_name in existing_names:
        counter += 1
        new_name = f"{target_name} ({counter})"
    return new_name

# Rename function to the history sidebar
def rename_project_in_history(all_history, old_name, new_name):
    """Updates the project name in the permanent JSON file with duplicate protection."""
    # 1. Generate a unique name based on what's already in history
    # We pass all_history to ensure we don't collide with existing names
    final_name = get_unique_name(all_history, new_name)
    
    # 2. Update the name in the list
    for item in all_history:
        if item["project"] == old_name:
            item["project"] = final_name
            break
            
    # 3. Save to the permanent file
    with open(HISTORY_FILE, "w") as f:
        json.dump(all_history, f, indent=4)
        
    return final_name

# --- LOAD PERMANENT HISTORY ---
all_history = load_history()

# --- STREAMLIT UI SETUP ---
st.title("🚀 AI Operational Hub")
st.write("Welcome to your program management dashboard.")

# --- SIDEBAR: PROJECT LIST ---
st.sidebar.header("Project List 📖")

# The New Project Popover
if st.sidebar.button("➕ New Project", use_container_width=True):
    new_project_dialog(should_trigger=False)

# --- MAIN DISPLAY FOR HISTORICAL ENTRIES ---
if "selected_analysis" in st.session_state:
    selected = st.session_state.selected_analysis
    
    # This box shows which historical record is active
    st.info(f"Viewing Historical Record: **{selected['project']}**")
    
    # Create two columns for side-by-side viewing
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Reasoning 🧠")
        st.write(selected['reasoning'])
    with col2:
            st.subheader("Requirements 📋")
            # 1. Get the tasks list from our selected analysis
            tasks_list = selected.get('tasks', [])

            # 2. Loop through the list and create checkboxes
            # We use the index 'i' to create a unique key for each checkbox
            for i, task_info in enumerate(tasks_list):
                # The 'value' is set to whatever is currently saved (True or False)
                # 1. Determine the display name based on status
                display_name = task_info['task']
                if task_info['done']:
                    # Apply green color, checkmark, and strikethrough
                    display_name = f":green[✅ {display_name}]"

                # 2. Create the checkbox with the new display name
                is_checked = st.checkbox(
                    display_name, 
                    value=task_info['done'], 
                    key=f"check_{selected['project']}_{i}",
                    on_change=close_archive # Close archive on any checkbox change
                )
                # 3. If the user clicks the checkbox, update the status in our history file
                if is_checked != task_info['done']:
                    # 1. Update the permanent file
                    update_task_status(all_history, selected['project'], i, is_checked)
                    # 2. Update the app's current memory so the color changes immediately
                    task_info['done'] = is_checked
                    # 3. Refresh the screen so the Archive closes and colors update
                    st.rerun()
                   
    st.markdown("---") # A clean line to separate sections

    # Add a way to go back to the "New Analysis" view
    if st.button("Close Historical View ❌", on_click=close_archive):
        del st.session_state.selected_analysis
        st.query_params.clear()
        st.rerun()
        
    st.divider() # Adds a line to separate history from the new input area

# --- USER INPUT AREA ---
user_input = st.text_area(
    "Paste your notes or workflow details here:", 
    height=200, 
    key="user_input_key"
    )

# ---ANALYZER BUTTON LOGIC ---
# 1. Setup variables needed for the AI call
knowledge_base = ""
if user_input:
    try:
        with open("guide.txt", "r") as f:
            knowledge_base = f.read()
    except FileNotFoundError:
        pass

# 2. Define the button labels and checks
if not st.session_state.get("current_project_name"):
    if st.button("Analyze Workflow 🚀", use_container_width=True):
        if not user_input or user_input.strip() == "":
            st.error("Please insert the information to be analyzed.")
        else:
            new_project_dialog(should_trigger=True)
else:
    btn_label = f"Analyze Workflow for: {st.session_state.current_project_name}"

    # The Bridge: If we are ready, do a quick rerun to ensure the dialog closes
    if st.session_state.get("analysis_ready"):
        st.session_state.analysis_ready = False
        st.session_state.trigger_analysis = True
        import time # We add this to give the browser time to close the dialog
        time.sleep(0.5)
        st.rerun()

    if st.button(btn_label, use_container_width=True, on_click=close_archive) or st.session_state.get("trigger_analysis"):  
        st.session_state.trigger_analysis = False  # Reset the trigger 
    
        with st.spinner("Analysing started."):
                # This prioritizes the notes captured just before the text area was cleared
                active_notes = st.session_state.get("temp_notes_buffer", user_input)
                # Initialize variables
                reasoning = ""
                final_answer = ""
                max_attempts = 3
                attempt = 0
                valid_response = False

                while attempt < max_attempts and not valid_response:
                    attempt += 1
                    response = client.chat.completions.create(
                        model="gpt-oss:20b",
                        messages=[
                            {
                                "role": "system", 
                                "content": (
                                    "You are a Senior Operational Excellence Consultant. "
                                    "STRICT REQUIREMENT: You must provide your output in two parts. "
                                    "1. Your reasoning/thought process. "
                                    "2. The string '---SEPARATOR---' on its own line. "
                                    "3. A JSON list of strings for the tasks. "
                                    "Example: Reasoning here... \n---SEPARATOR---\n[\"Task 1\"]"
                                    '["Task 1", "Task 2", "Task 3"]'
                                )
                            },
                            {
                                "role": "user", 
                                "content": f"Guide:\n{knowledge_base}\n\nNotes:\n{user_input}"
                            }
                        ],
                        temperature=0.7 # Slight randomness helps avoid repeating the same mistake
                    )
                    
                    full_response = response.choices[0].message.content

                    if full_response and "---SEPARATOR---" in full_response:
                        reasoning, final_answer = full_response.split("---SEPARATOR---", 1)
                        
                        try:
                            tasks=parse_tasks(final_answer.strip())
                            save_to_history(st.session_state.current_project_name, reasoning.strip(), final_answer.strip())

                            st.session_state.selected_analysis = {
                                "project": st.session_state.current_project_name,
                                "reasoning": reasoning.strip(),
                                "tasks": tasks
                            }
                            valid_response = True
                        except Exception:
                            # If parsing fails, we treat it as an invalid response to trigger a retry
                            continue
                if valid_response:
                    st.session_state.pending_clear_notes = True
                    if "current_project_name" in st.session_state:
                        del st.session_state.current_project_name
                    st.query_params["view"] = "results"
                    st.rerun()
                else:
                        st.error(f"🚨 Please refresh the page and try again.")

# --- SIDEBAR PERMANENT HISTORY ---
st.sidebar.divider()
st.sidebar.subheader("Permanent History 📂")

# Main History Loop
for idx, item in enumerate(list(all_history)): 
    col_btn, col_menu = st.sidebar.columns([0.8, 0.2])
    
    # Check if this specific item is being renamed
    rename_key = f"renaming_{idx}"
    
    with col_btn:
        if st.session_state.get(rename_key, False):
            # --- RENAME MODE: Show Text Input ---
            new_name = st.text_input(
                "New Name",
                value=item['project'],
                key=f"input_{idx}",
                label_visibility="collapsed",
            )
            # If user presses Enter or changes focus, save it
            if new_name != item['project']:
                # The function now handles the (1), (2) logic for us
                rename_project_in_history(all_history, item['project'], new_name)
                st.session_state[rename_key] = False
                st.rerun()
        else:
            # --- NORMAL MODE: Show Folder Button ---
            if st.button(f"📁 {item['project']}", key=f"btn_{idx}", use_container_width=True):
                st.session_state.selected_analysis = item 
                st.session_state.archive_open = False 
                st.rerun()
            
    with col_menu:
        # We create a dynamic key using a session_state counter or the rename state
        # This forces the popover to "reset" and close after a rerun
        popover_key = f"popover_{idx}_{st.session_state.get(rename_key, False)}"
        
        with st.popover("⋮", use_container_width=True):
            
            # --- RENAME BUTTON ---
            if st.button("Rename ✏️", key=f"ren_opt_{idx}", use_container_width=True, on_click=close_archive):
                st.session_state[rename_key] = True
                st.rerun() 
                
            # --- DELETE BUTTON ---
            if st.button("Delete 🗑️", key=f"del_opt_{idx}", use_container_width=True, on_click=close_archive):
                deleted = delete_from_history(all_history, item['project'])
                if deleted:
                    deleted['original_index'] = idx 
                    st.session_state.trash_archive.append(deleted)
                
                if st.session_state.get("selected_analysis", {}).get("project") == item['project']:
                    del st.session_state.selected_analysis
                
                st.rerun()

# --- RECENTLY DELETED ARCHIVE ---
if st.session_state.get("trash_archive"):
    st.sidebar.markdown("---")
    
    # 1. Determine the label based on the current state
    arch_label = "Hide Recently Deleted ❌" if st.session_state.archive_open else "Show Recently Deleted 🗑️"

    # 2. Create the full-width button that flips the state
    if st.sidebar.button(arch_label, use_container_width=True):
        st.session_state.archive_open = not st.session_state.archive_open
        st.rerun()

    if st.session_state.archive_open:
        # We use an 'indent' or a container to make it look grouped
        with st.sidebar.container(border=True):
            for arch_idx, arch_item in enumerate(reversed(st.session_state.trash_archive)):
                col_arch_name, col_restore = st.columns([0.8, 0.2])
                
                with col_arch_name:
                    st.markdown(f"**{arch_item['project']}**")
                
                with col_restore:
                    # We remove the calculation from the top and set the state directly here
                    if st.button("↩️", key=f"restore_{arch_idx}", help="Restore"):
                        history = load_history()
                        pos = arch_item.get('original_index', 0)
                        history.insert(pos, arch_item)
                        
                        with open(HISTORY_FILE, "w") as f:
                            json.dump(history, f, indent=4)
                        
                        real_idx = len(st.session_state.trash_archive) - 1 - arch_idx
                        st.session_state.trash_archive.pop(real_idx)
                        
                        # Explicitly keep it open
                        open_archive() 
                        st.rerun()