import os
from uuid import uuid4
from streamlit_local_storage import LocalStorage
from openai import OpenAI
from google.genai import types
import json
import streamlit as st
import re
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Streamlit page config
st.set_page_config(layout="wide")

# Secrets from Streamlit or locally
def get_secret(key):
    try:
        if key in st.secrets: #Streamlit secrets
            return st.secrets[key]
    except (FileNotFoundError, Exception):
        pass 
    return os.getenv(key) #local env fetch

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
if "run_ai_now" not in st.session_state:
    st.session_state.run_ai_now = False
if "user_input_key" not in st.session_state:
    st.session_state.user_input_key = "I need an open job, I only have a SAN and CA" # DEBUG TEXT --- REMOVE IN PRODUCTION

# User history
ls=LocalStorage()
STORAGE_KEY="user_history_v1"
# Load 
def get_history():
    if "local_history_cache" in st.session_state:
        return st.session_state.local_history_cache
    stored_data=ls.getItem(STORAGE_KEY)
    if stored_data is not None:
        st.session_state.local_history_cache=stored_data
        return stored_data
    return []
def save_whole_history(history_data):
    st.session_state.local_history_cache = history_data
    ls.setItem(STORAGE_KEY, history_data)

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

def save_to_history(project_name, reasoning, tasks):
    history = get_history()
    # Create new entry
    new_entry = {
        "id": uuid4().hex,
        "project": project_name,
        "reasoning": reasoning,
        "tasks": tasks
    }
    history.insert(0, new_entry)
    save_whole_history(history)

def update_task_status(project_id, task_index, new_status):
    current_history=get_history()
    for item in current_history:
        if item["id"] == project_id:
            item["tasks"][task_index]["done"] = new_status
            break
    save_whole_history(current_history)

def delete_from_history(project_id):
    current_history = get_history()
    deleted_item = None
    new_history = []
    
    for item in current_history:
        if item["id"] == project_id and deleted_item is None:
            deleted_item = item
        else:
            new_history.append(item)
            
    if deleted_item:
        save_whole_history(new_history)
            
    return deleted_item

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
def rename_project_in_history(project_id, new_name):
    current_history = get_history()
    final_name = get_unique_name(current_history, new_name)
    
    for item in current_history:
        if item["id"] == project_id:
            item["project"] = final_name
            break
            
    save_whole_history(current_history)
    return final_name

# --- HYBRID AI ENGINE ---
def analysis_engine(kb, notes):
    st.info("Analysis started")
    
    # 1. Check if we are using Gemini (Cloud) or Ollama (Local)
    target_model = get_secret("AI_MODEL_NAME") or "gpt-oss:20b"
    is_google_native = "gemini" in target_model.lower()
    
    # Convert old Gemini model names to new format
    if is_google_native:
        # Remove "models/" prefix if present
        target_model = target_model.replace("models/", "")
        # Map old model names to new equivalents
        model_mapping = {
            "gemini-1.5-flash-latest": "gemini-2.5-flash",
            "gemini-1.5-flash": "gemini-2.5-flash",
            "gemini-1.5-pro-latest": "gemini-2.5-pro",
            "gemini-1.5-pro": "gemini-2.5-pro",
            "gemini-pro": "gemini-2.5-pro",
            "gemini-flash": "gemini-2.5-flash"
        }
        # Use mapping if available, otherwise keep as is but ensure it's a valid new format
        target_model = model_mapping.get(target_model, target_model)

    with st.spinner("Please wait a few seconds..."):
        # Setup inputs
        user_message = f"Guide:\n{kb}\n\nNotes:\n{notes}"

        # System prompt (Identical for both)
        system_instruction = (
            "You are a Senior Operational Excellence Consultant. "
            "STRICT REQUIREMENT: You must provide your output as a SINGLE VALID JSON OBJECT. "
            "The JSON must have exactly two keys: "
            "1. 'reasoning': A string explaining your thought process. "
            "2. 'tasks': A list of strings for the actionable steps. "
            "Do not include markdown formatting (like ```json). Just the raw JSON object."
        )

        attempt = 0 
        valid_response = False
        max_attempts = 3

        while attempt < max_attempts and not valid_response:
            attempt += 1
            try:
                full_response = ""

                # --- PATH A: GEMINI NATIVE (Fixes Cloud 404) ---
                if is_google_native:
                    genai_client = genai.Client(api_key=get_secret("AI_API_KEY"))
                    response = genai_client.models.generate_content(
                        model=target_model,
                        contents=user_message,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.2
                        )
                    )
                    full_response = response.text

                # --- PATH B: OLLAMA / OPENAI (Your original code) ---
                else:
                    # API Client Setup
                    client=OpenAI(
                        base_url=get_secret("AI_BASE_URL"),
                        api_key=get_secret("AI_API_KEY")
                    )
                    response = client.chat.completions.create(
                        model=target_model,
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7,
                        timeout=120
                    )
                    full_response = response.choices[0].message.content

                # --- COMMON PARSING (Kept exactly as is) ---
                if full_response:
                    try:
                        clean_text = full_response.replace("```json", "").replace("```", "").strip() # cleaning AI response
                        data = json.loads(clean_text) # parsing
                        reasoning = data.get("reasoning", "No reasoning provided.")
                        task_names = data.get("tasks", [])
                        tasks = [{"task": name, "done": False} for name in task_names]
                        save_to_history(st.session_state.current_project_name, reasoning, tasks)

                        st.session_state.selected_analysis = {
                            "project": st.session_state.current_project_name,
                            "reasoning": reasoning,
                            "tasks": tasks
                        }
                        valid_response = True
                        
                    except json.JSONDecodeError:
                        st.warning(f"Attempt {attempt}: AI did not return valid JSON. Retrying...")
                        continue
                    except Exception as e:
                        st.warning(f"Attempt {attempt}: Parsing error: {e}")
                        continue
                else:
                    st.warning(f"Attempt {attempt}: Empty response. Retrying...")
                
            except Exception as e:
                st.error(f"Error ({'Gemini' if is_google_native else 'Ollama'}): {e}")
                continue

        # Final Cleanup
        if valid_response:
            st.session_state.run_ai_now = False 
            if "current_project_name" in st.session_state:
                del st.session_state.current_project_name
            st.session_state.pending_clear_notes = True
            st.query_params["view"] = "results"
            st.rerun()
        else:
            st.session_state.run_ai_now = False
            st.error("🚨 Please refresh the page and try again.")

# load history file
all_history = get_history()

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

if st.session_state.get("run_ai_now"):
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
                    display_name = f":green[{display_name}]"

                # new checkbox -------- to be reviewed
                is_checked = st.checkbox(
                    display_name, 
                    value=task_info['done'], 
                    key=f"check_{selected['project']}_{i}",
                    on_change=close_archive # Close archive
                )
                # 3. status auto update in history file
                if is_checked != task_info['done']:
                    # update_task_status( selected['project'], i, is_checked)
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
        if not user_input or not user_input.strip():
            st.error("Please enter some notes to be analyzed.")
        else:
            if not st.session_state.get("current_project_name"):
                st.session_state.show_inline_new = True
                st.rerun()
            else:
                st.session_state.run_ai_now = True
                st.rerun()

# Sidebar Perm history display
st.sidebar.divider()
st.sidebar.subheader("Permanent History 📂")

for idx, item in enumerate(list(all_history)):
    # Rows 
    col_btn, col_menu = st.sidebar.columns([0.85, 0.15])
    rename_key = f"renaming_{idx}"
    options_key = f"show_opts_{idx}" 
    
    active_id=st.session_state.get("selected_analysis", {}).get("id")
    is_active=(active_id==item["id"])

    btn_type = "primary" if is_active else "secondary"
    
    # Pj button
    new_name = str(item['project'])

    if st.session_state.get(rename_key, False):
        new_name = st.sidebar.text_input(
            "New Name",
            value=item['project'],
            key=f"input_{item['id']}_{idx}", 
            label_visibility="collapsed",
        )
    else:
        with col_btn:
            if st.button(f"📁 {item['project']}", key=f"btn_{idx}", use_container_width=True, type=btn_type):
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
                    rename_project_in_history(item['id'], new_name)
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
                deleted = delete_from_history(item['id'])
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
                col_arch_name, col_restore = st.columns([0.90, 0.10])
                
                with col_arch_name:
                    st.markdown(f"**{arch_item['project']}**")
                
                with col_restore:
                    if st.button("↩️", key=f"restore_{arch_idx}", help="Restore"):
                        history = get_history()
                        # Get original spot or default to top
                        pos = arch_item.get('original_index', 0)
                        
                        # Safety: ensure position isn't larger than the list
                        if pos > len(history):
                            pos = len(history)
                            
                        history.insert(pos, arch_item)
                        save_whole_history(history)
                        
                        # Calculate real index to remove from trash
                        real_idx = len(st.session_state.trash_archive) - 1 - arch_idx
                        st.session_state.trash_archive.pop(real_idx)
                        
                        # Stay open after restore
                        open_archive() 
                        st.rerun()

            st.markdown("---")
            if st.button("Clear All 🗑️", use_container_width=True):
                st.session_state.trash_archive = []
                st.session_state.archive_open = False
                st.rerun()

# DELETE - leftovers                    
for k in list(st.session_state.keys()):
    if str(k).startswith("kill_pop_"):
        st.session_state[k] = False
