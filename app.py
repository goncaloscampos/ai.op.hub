import os
from dotenv import load_dotenv
from openai import OpenAI
import json
import streamlit as st
import re

load_dotenv()
# Secrets from Streamlit or locally
def get_secret(key):
    if key in st.secrets:
        return st.secrets[key]
    return os.getenv(key)

# Streamlit page config
st.set_page_config(layout="wide")

# Session state cleanup for notes
if st.session_state.get("pending_clear_notes"):
    st.session_state.user_input_key = ""
    st.session_state.pending_clear_notes = False

def close_archive():
    st.session_state.archive_open = False
def open_archive():
    st.session_state.archive_open = True

# Initialize session state variables
if "archive_open" not in st.session_state:
    st.session_state.archive_open = False
if "trash_archive" not in st.session_state:
    st.session_state.trash_archive = []
if "analysis_ready" not in st.session_state:
    st.session_state.analysis_ready = False
if "trigger_analysis" not in st.session_state:
    st.session_state.trigger_analysis = False
if "run_ai_now" not in st.session_state:
    st.session_state.run_ai_now = False
if "sidebar_breaker" not in st.session_state:
    st.session_state.sidebar_breaker = False
if "user_input_key" not in st.session_state:
    st.session_state.user_input_key = "I need an open job, I only have a SAN and CA" # DEBUG TEXT --- REMOVE IN PRODUCTION

# API Client Setup
client=OpenAI(
    base_url=os.getenv("AI_BASE_URL"),
    api_key=os.getenv("AI_API_KEY")
)
HISTORY_FILE = "history_log.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []

# Format the AI response and convert the JSON list into checkboxes
def parse_tasks(text):
    # Search for a pattern starting with [ and ending with ]
    match = re.search(r'\[.*\]', text, re.DOTALL)
    
    if match:
        # Extract only the bracketed part
        clean_json = match.group(0)
        task_names = json.loads(clean_json)
        # Create the list of task dictionaries
        return [{"task": name, "done": False} for name in task_names]
    
    # If no brackets are found, trigger the fallback
    raise ValueError("No JSON list found")

def save_to_history(project_name, reasoning, plan_text):
    history = load_history()
    new_entry = {
        "project": project_name,
        "reasoning": reasoning.strip(),
        "tasks": parse_tasks(plan_text) # Process the text here!
    }
    history.insert(0, new_entry) # Top to bottom
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

# Pj task status update
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
        if item["project"] == project_name and deleted_item is None:
            deleted_item = item
        else:
            new_history.append(item)
    
    # Only write to the file if we actually removed something
    if deleted_item:
        with open(HISTORY_FILE, "w") as f:
            json.dump(new_history, f, indent=4)
            
    return deleted_item

def analysis_engine(kb, notes):
    # AI Call logic here
    st.info("Analysis started")
    with st.spinner("Please wait a few seconds..."):
            # This prioritizes the notes captured just before the text area was cleared
            captured_notes = notes
            # Initialize variables
            reasoning = ""
            final_answer = ""
            max_attempts = 3
            attempt = 0
            valid_response = False

            target_model=get_secret("AI_MODEL_NAME") or "gpt-oss:20b"

            while attempt < max_attempts and not valid_response:
                attempt += 1
                try:
                    response = client.chat.completions.create(
                        model=target_model,
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
                                "content": f"Guide:\n{kb}\n\nNotes:\n{notes}"
                            }
                        ],
                        temperature=0.7, # Randomness control
                        timeout=120 # 2 minutes timeout
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
                        except ValueError:
                            # Parsing failed, will retry - st.warning to user 
                            st.warning(f"Attempt {attempt}: Your computer needs vacations. Asking it nicely this time...")
                            continue
                except Exception as e:
                    st.error(f"Error during AI processing: {e}") # st.error - to the terminal
                    continue

            if valid_response:
                st.session_state.run_ai_now = False # Clears the trigger so the Overlay doesn't catch it again
                if "current_project_name" in st.session_state:
                    del st.session_state.current_project_name
                st.session_state.pending_clear_notes = True
                st.query_params["view"] = "results"
                st.rerun()
            else:
                st.session_state.run_ai_now = False # Clears the trigger so the Overlay doesn't catch it again
                st.error(f"🚨 Please refresh the page and try again.")

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
    # (avoids name collisions)
    final_name = get_unique_name(all_history, new_name)
    
    # name update in memory
    for item in all_history:
        if item["project"] == old_name:
            item["project"] = final_name
            break
            
    # save to perm file
    with open(HISTORY_FILE, "w") as f:
        json.dump(all_history, f, indent=4)
        
    return final_name

# load history file
all_history = load_history()

# UI at the top
st.title("🚀 AI Operational Hub")
st.write("Welcome to your program management dashboard.")

# ---ANALYZER BUTTON LOGIC ---
# Setup variables needed for the AI call
knowledge_base = ""
if st.session_state.get("user_input_key"):
    try:
        with open("guide.txt", "r") as f:
            knowledge_base = f.read()
    except FileNotFoundError:
        pass

if st.session_state.get("run_ai_now") and not st.session_state.get("show_new_project_dialog"):
    captured_notes = st.session_state.get("user_input_key", "")
    analysis_engine(knowledge_base, captured_notes)
    st.stop()

# Siderbar - Project List and New Project Creation
with st.sidebar:
    st.sidebar.header("Project List 📖")

    # 1. state control for inline UI
    if "show_inline_new" not in st.session_state:
        st.session_state.show_inline_new = False

    # 2. button to toggle the inline UI
    if not st.session_state.show_inline_new:
        if st.button("➕ New Project", use_container_width=True, key="btn_sidebar_new"):
            st.session_state.show_inline_new = True
            st.rerun()
    
    # 3. inline UI
    if st.session_state.show_inline_new:
        if st.session_state.show_inline_new:
                with st.container(border=True):
                    with st.sidebar.form("new_project_form"):
                        st.write("Enter Project Name:")
                        new_proj_name = st.text_input(
                            "Project Name", 
                            placeholder="e.g. Client - Job Name",
                            label_visibility="collapsed"
                        )
                        c1, c2 = st.columns(2)
                        with c1:
                            submitted = st.form_submit_button("Create ✅", use_container_width=True)
                        with c2:
                            cancelled = st.form_submit_button("Cancel ❌", use_container_width=True)
                        
                        if cancelled:
                            st.session_state.show_inline_new = False
                            st.rerun()
                        
                        elif submitted:
                            current_notes = st.session_state.get("user_input_key", "").strip()
                            if not new_proj_name.strip():
                                st.error("Name required")
                            elif not current_notes:
                                st.error("No notes found to analyze!")
                            else:
                                # success logic
                                final_name = get_unique_name(all_history, new_proj_name)
                                st.session_state.current_project_name = final_name
                                # note clearing
                                if "selected_analysis" in st.session_state:
                                    del st.session_state.selected_analysis
                                
                                st.session_state.show_inline_new = False
                                st.session_state.run_ai_now = True
                                st.rerun()

# Display history entries
if "selected_analysis" in st.session_state:
    selected = st.session_state.selected_analysis
    
    # This box shows which historical record is active
    st.info(f"Viewing Historical Record: **{selected['project']}**")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Reasoning 🧠")
        st.write(selected['reasoning'])
    with col2:
            st.subheader("Requirements 📋")
            # 1. Get the tasks list from our selected analysis
            tasks_list = selected.get('tasks', [])

            # 2. tasks in checkboxes (i for unique key)
            for i, task_info in enumerate(tasks_list):
                display_name = task_info['task']
                if task_info['done']:
                    # Apply green color, checkmark ------- to be reviewed
                    display_name = f":green[✅ {display_name}]"

                # new checkbox -------- to be reviewed
                is_checked = st.checkbox(
                    display_name, 
                    value=task_info['done'], 
                    key=f"check_{selected['project']}_{i}",
                    on_change=close_archive # Close archive
                )
                # 3. status auto update in history file
                if is_checked != task_info['done']:
                    update_task_status(all_history, selected['project'], i, is_checked)
                    task_info['done'] = is_checked
                    st.rerun()
                   
    st.markdown("---") # Divider -------------- to be reviewed vs st.divider()

    # "new analysis" button
    if st.button("Close Historical View ❌", on_click=close_archive):
        del st.session_state.selected_analysis
        st.query_params.clear()
        st.rerun()
        
    st.divider() # Divider -------------- to be reviewed vs st.markdown("---")

# User text input area
with st.form("analysis_form"):
    user_input = st.text_area(
        "Paste your notes or workflow details here:", 
        height=200, 
        key="user_input_key"
    )
    submitted = st.form_submit_button("Analyze Workflow 🚀", use_container_width=True)
    if submitted:
        if not user_input or user_input.strip():
            st.error("Please enter some notes to be analyzed.")
        else:
            if not st.session_state.get("current_project_name"):
                st.session_state.show_inline_new = True
                st.session_state.show_new_project_dialog = True
                st.rerun()
            else:
                st.session_state.run_ai_now = True
                st.rerun()

# Sidebar Perm history display
st.sidebar.divider()
st.sidebar.subheader("Permanent History 📂")

for idx, item in enumerate(list(all_history)):
    # Rows 
    col_btn, col_menu = st.sidebar.columns([0.8, 0.2])
    rename_key = f"renaming_{idx}"
    options_key = f"show_opts_{idx}" 
    
    # Pj button
    new_name = str(item['project'])

    if st.session_state.get(rename_key, False):
        new_name = st.sidebar.text_input(
            "New Name",
            value=item['project'],
            key=f"input_{item['project']}_{idx}", 
            label_visibility="collapsed",
        )
    else:
        with col_btn:
            if st.button(f"📁 {item['project']}", key=f"btn_{idx}", use_container_width=True):
                st.session_state.selected_analysis = item 
                st.session_state.archive_open = False 
                st.rerun()

    # Rname Save/Cancel buttons
    if st.session_state.get(rename_key, False):
        save_col, cancel_col = st.sidebar.columns(2) 
        with save_col:
            # Input validation !
            is_valid_input = isinstance(new_name, str) and new_name.strip() != ""
            
            if st.button("Save ✅", key=f"save_{idx}", use_container_width=True) or (new_name != item['project'] and is_valid_input):
                if new_name != item['project'] and is_valid_input:
                    rename_project_in_history(all_history, item['project'], new_name)
                st.session_state[rename_key] = False
                st.rerun()
        with cancel_col:
            if st.button("Cancel ❌", key=f"can_{idx}", use_container_width=True):
                st.session_state[rename_key] = False
                st.rerun()
                
    with col_menu:
        if st.button("⋮", key=f"toggle_{idx}", use_container_width=True):
            st.session_state[options_key] = not st.session_state.get(options_key, False)
            st.rerun()

    # Options: Rename / Delete
    if st.session_state.get(options_key, False):
        opt_col1, opt_col2 = st.sidebar.columns(2)
        with opt_col1:
            if st.button("Rename ✏️", key=f"ren_opt_{idx}", use_container_width=True):
                st.session_state[rename_key] = True
                st.session_state[options_key] = False 
                st.rerun()
        with opt_col2:
            if st.button("Delete 🗑️", key=f"del_opt_{idx}", use_container_width=True):
                close_archive()
                deleted = delete_from_history(all_history, item['project'])
                if deleted:
                    deleted['original_index'] = idx 
                    st.session_state.trash_archive.append(deleted)
                
                if st.session_state.get("selected_analysis", {}).get("project") == item['project']:
                    del st.session_state.selected_analysis
                
                st.session_state[options_key] = False 
                st.rerun()

# Deleted history
if st.session_state.get("trash_archive"):
    st.sidebar.markdown("---")
    
    # Hide/Show btn logic
    arch_label = "Hide Recently Deleted ❌" if st.session_state.archive_open else "Show Recently Deleted 🗑️"

    # Hide/show btn
    if st.sidebar.button(arch_label, use_container_width=True):
        st.session_state.archive_open = not st.session_state.archive_open
        st.rerun()

    if st.session_state.archive_open:
        with st.sidebar.container(border=True):
            for arch_idx, arch_item in enumerate(reversed(st.session_state.trash_archive)):
                col_arch_name, col_restore = st.columns([0.8, 0.2])
                
                with col_arch_name:
                    st.markdown(f"**{arch_item['project']}**")
                
                with col_restore:
                    if st.button("↩️", key=f"restore_{arch_idx}", help="Restore"):
                        history = load_history()
                        pos = arch_item.get('original_index', 0)
                        history.insert(pos, arch_item)
                        # Save updated history
                        with open(HISTORY_FILE, "w") as f:
                            json.dump(history, f, indent=4)
                        # Remove from trash
                        real_idx = len(st.session_state.trash_archive) - 1 - arch_idx
                        st.session_state.trash_archive.pop(real_idx)
                        
                        # Stay open after restore
                        open_archive() 
                        st.rerun()

# Reset all popovers when the main script finishes                       
for k in list(st.session_state.keys()):
    if str(k).startswith("kill_pop_"):
        st.session_state[k] = False
