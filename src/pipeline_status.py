"""
Pipeline Status Tracker for BlueHorseshoe.

Standalone CLI tool for reading/writing pipeline status to a JSON file.
No bluehorseshoe package imports — fully standalone.

Usage:
    python src/pipeline_status.py begin               # Initialize new pipeline run
    python src/pipeline_status.py start <step>         # Mark step as running
    python src/pipeline_status.py complete <step>      # Mark step as completed
    python src/pipeline_status.py fail <step> <msg>    # Mark step as failed
    python src/pipeline_status.py progress <cur> <tot> # Update prediction progress
    python src/pipeline_status.py finish               # Mark pipeline as done
    python src/pipeline_status.py show                 # Display formatted status
"""
import fcntl
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
STATUS_FILE = os.path.join(_REPO_ROOT, "src", "logs", "pipeline_status.json")
STEPS = ["update", "predict", "report", "email", "evaluate"]


def load_status():
    """Load pipeline status from JSON file with file locking."""
    if not os.path.exists(STATUS_FILE):
        return None
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return data
    except (json.JSONDecodeError, IOError):
        return None


def save_status(data):
    """Save pipeline status to JSON file with file locking."""
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)


def begin_pipeline():
    """Initialize a new pipeline run, resetting all steps to pending."""
    data = {
        "pipeline_start": datetime.now().isoformat(timespec="seconds"),
        "pipeline_end": None,
        "current_step": None,
        "steps": {step: {"status": "pending"} for step in STEPS},
        "last_updated": None,
        "error": None,
    }
    save_status(data)


def finish_pipeline():
    """Mark the pipeline as done."""
    data = load_status()
    if data is None:
        print("No pipeline run found.", file=sys.stderr)
        return
    data["pipeline_end"] = datetime.now().isoformat(timespec="seconds")
    data["current_step"] = None
    save_status(data)


def start_step(name):
    """Mark a step as running and record its start time."""
    if name not in STEPS:
        print(f"Unknown step: {name}. Valid: {STEPS}", file=sys.stderr)
        sys.exit(1)
    data = load_status()
    if data is None:
        print("No pipeline run found. Call 'begin' first.", file=sys.stderr)
        sys.exit(1)
    data["current_step"] = name
    data["steps"][name] = {
        "status": "running",
        "start": datetime.now().isoformat(timespec="seconds"),
    }
    save_status(data)


def complete_step(name):
    """Mark a step as completed and calculate its duration."""
    if name not in STEPS:
        print(f"Unknown step: {name}. Valid: {STEPS}", file=sys.stderr)
        sys.exit(1)
    data = load_status()
    if data is None:
        print("No pipeline run found.", file=sys.stderr)
        sys.exit(1)
    step = data["steps"][name]
    now = datetime.now().isoformat(timespec="seconds")
    step["status"] = "completed"
    step["end"] = now
    if "start" in step:
        start_dt = datetime.fromisoformat(step["start"])
        end_dt = datetime.fromisoformat(now)
        step["duration_sec"] = int((end_dt - start_dt).total_seconds())
    # Clear progress if present
    step.pop("progress", None)
    save_status(data)


def fail_step(name, error_msg):
    """Mark a step as failed with an error message."""
    if name not in STEPS:
        print(f"Unknown step: {name}. Valid: {STEPS}", file=sys.stderr)
        sys.exit(1)
    data = load_status()
    if data is None:
        print("No pipeline run found.", file=sys.stderr)
        sys.exit(1)
    step = data["steps"][name]
    now = datetime.now().isoformat(timespec="seconds")
    step["status"] = "failed"
    step["end"] = now
    if "start" in step:
        start_dt = datetime.fromisoformat(step["start"])
        end_dt = datetime.fromisoformat(now)
        step["duration_sec"] = int((end_dt - start_dt).total_seconds())
    data["error"] = error_msg
    save_status(data)


def update_progress(current, total):
    """Update the predict step's progress dict."""
    data = load_status()
    if data is None:
        return
    step = data["steps"].get("predict", {})
    if step.get("status") != "running":
        return
    pct = round((current / total) * 100, 1) if total > 0 else 0.0
    step["progress"] = {
        "current": int(current),
        "total": int(total),
        "percent": pct,
    }
    data["steps"]["predict"] = step
    save_status(data)


def _format_duration(seconds):
    """Format seconds into a human-readable string."""
    if seconds is None:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _progress_bar(percent, width=20):
    """Build a progress bar string."""
    filled = int(width * percent / 100)
    empty = width - filled
    return "\u2588" * filled + "\u2591" * empty


def show_status():
    """Display formatted terminal status."""
    data = load_status()
    if data is None:
        print("  No pipeline status found.")
        print("  Run the daily pipeline to see status here.")
        return

    # Header
    start_str = ""
    if data.get("pipeline_start"):
        try:
            dt = datetime.fromisoformat(data["pipeline_start"])
            start_str = dt.strftime("%b %d, %Y  %-I:%M %p")
        except (ValueError, TypeError):
            start_str = data["pipeline_start"]

    # Calculate elapsed time
    elapsed_str = ""
    if data.get("pipeline_start"):
        start_dt = datetime.fromisoformat(data["pipeline_start"])
        if data.get("pipeline_end"):
            end_dt = datetime.fromisoformat(data["pipeline_end"])
        else:
            end_dt = datetime.now()
        elapsed = int((end_dt - start_dt).total_seconds())
        elapsed_str = _format_duration(elapsed)
        if data.get("pipeline_end"):
            elapsed_str += " (done)"

    print()
    print("  BlueHorseshoe Pipeline Status")
    print("  " + "\u2500" * 35)
    if start_str:
        print(f"  Started: {start_str}")
    if elapsed_str:
        print(f"  Elapsed: {elapsed_str}")
    print()

    # Steps
    step_labels = {
        "update": "Update Data",
        "predict": "Predict",
        "report": "Report",
        "email": "Email",
    }

    for step_name in STEPS:
        step = data["steps"].get(step_name, {"status": "pending"})
        status = step.get("status", "pending")
        label = step_labels.get(step_name, step_name)
        duration = step.get("duration_sec")

        if status == "completed":
            icon = "\u2713"
            dur_str = f"  {_format_duration(duration)}" if duration is not None else ""
            print(f"  {icon} {label:<20s}{dur_str}")
        elif status == "running":
            icon = "\u25b6"
            # Calculate running duration
            running_dur = ""
            if "start" in step:
                start_dt = datetime.fromisoformat(step["start"])
                running_secs = int((datetime.now() - start_dt).total_seconds())
                running_dur = f"  {_format_duration(running_secs)}"

            progress = step.get("progress")
            if progress:
                pct = progress.get("percent", 0)
                bar = _progress_bar(pct)
                print(f"  {icon} {label:<20s}{running_dur}   [{bar}] {pct:.0f}%")
            else:
                print(f"  {icon} {label:<20s}{running_dur}")
        elif status == "failed":
            icon = "\u2717"
            dur_str = f"  {_format_duration(duration)}" if duration is not None else ""
            print(f"  {icon} {label:<20s}{dur_str}  FAILED")
        else:
            print(f"    {label:<20s}pending")

    # Error
    if data.get("error"):
        print()
        print(f"  Error: {data['error']}")

    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python pipeline_status.py <command> [args]")
        print("Commands: begin, start, complete, fail, progress, finish, show")
        sys.exit(1)

    command = sys.argv[1]

    if command == "begin":
        begin_pipeline()
    elif command == "finish":
        finish_pipeline()
    elif command == "start":
        if len(sys.argv) < 3:
            print("Usage: python pipeline_status.py start <step>", file=sys.stderr)
            sys.exit(1)
        start_step(sys.argv[2])
    elif command == "complete":
        if len(sys.argv) < 3:
            print("Usage: python pipeline_status.py complete <step>", file=sys.stderr)
            sys.exit(1)
        complete_step(sys.argv[2])
    elif command == "fail":
        if len(sys.argv) < 4:
            print("Usage: python pipeline_status.py fail <step> <message>", file=sys.stderr)
            sys.exit(1)
        fail_step(sys.argv[2], " ".join(sys.argv[3:]))
    elif command == "progress":
        if len(sys.argv) < 4:
            print("Usage: python pipeline_status.py progress <current> <total>", file=sys.stderr)
            sys.exit(1)
        update_progress(int(sys.argv[2]), int(sys.argv[3]))
    elif command == "show":
        show_status()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
