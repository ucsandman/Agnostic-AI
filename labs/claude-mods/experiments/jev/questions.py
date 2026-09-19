"""The judgment definitions shared by every backend (Jev, Claude Haiku via `claude -p`, or a deterministic stub).

Each question is a plain dict in TypeSafe's wire shape (type/instructions/criteria), so the SAME definition
is what Jev receives and what the fallback backends are prompted with. Question ids are for code only.
"""

LEG_QUESTIONS = {
    "phase": {
        "type": "choice",
        "instructions": "Look at `last_user_prompt`, `recent_tool_calls_oldest_first` and `last_model_step`. Which phase of coding-agent work is the session in right now?",
        "criteria": {
            "planning": "Reading, searching or exploring; no files changed yet; deciding what to do",
            "implementation": "Editing files or running commands that change things; a task is actively being carried out",
            "verification": "Running tests, checking results, a subagent reporting back, confirming that work succeeded",
            "recovery": "Handling a failure, a denial or an error: retrying, working around a refusal, fixing a broken attempt",
            "idle": "No turn is open (`session.turn_open` is false); the last turn finished and nothing is in flight",
        },
    },
    "work_in_progress": {
        "type": "noul",
        "instructions": "Is important work still in progress right now: an open turn, a tool call in flight, a subagent running, or an edit started but not finished?",
        "criteria": {
            "true": "Something is mid-flight and interrupting now would cut it off",
            "false": "Nothing is in flight; the last action completed and the model has stopped",
        },
    },
    "clean_boundary": {
        "type": "noul",
        "instructions": "Would handing this session over to a different coding agent RIGHT NOW be a clean boundary, with no half-done action and no pending answer the current agent still owes?",
        "criteria": {
            "true": "The turn is closed, no tool call or subagent is running, the working tree is coherent enough to describe",
            "false": "A turn is open, a call or subagent is running, or a dialog is waiting",
        },
    },
    "continuity_loss_risk": {
        "type": "score",
        "instructions": "If the session were handed off at this instant with only the information visible in this state, how much continuity would the next agent lose?",
        "criteria": [
            "Nothing: the state is self-describing and complete",
            "A little: minor context such as why the last command was run",
            "A lot: a multi-step task is half done and its plan lives only in the current agent's context",
            "Severe: an action is mid-flight or a human answer is pending; the next agent could not know what to do",
        ],
    },
    "blocked_on_human": {
        "type": "noul",
        "instructions": "Is the session currently waiting on a human (a dialog, a permission prompt, an approval) rather than on the model or a tool?",
        "criteria": {
            "true": "A question or approval dialog is open and the human has not answered",
            "false": "No human input is being awaited",
        },
    },
}
COST_QUESTIONS = {
    "tool_thrashing": {
        "type": "noul",
        "instructions": "Looking at `recent_tool_calls_oldest_first` and `permission_denials_so_far` if present: is the agent thrashing, i.e. issuing repeated tool calls that keep failing, being denied, or not advancing the task?",
        "criteria": {
            "true": "Repeated failures or denials with the same approach; little or no progress between calls",
            "false": "Calls succeed and each advances the task",
        },
    },
    "unnecessary_reread": {
        "type": "noul",
        "instructions": "In `recent_tool_calls_oldest_first`, is the same file being read again without an intervening edit to it, so that the re-read adds no new information?",
        "criteria": {
            "true": "The same file_path was Read two or more times with no Edit or Write of that file in between",
            "false": "Each Read is of a new file or follows a change to that file",
        },
    },
    "loop_state": {
        "type": "choice",
        "instructions": "Overall, is this session's recent activity productive iteration, a stuck loop, or finished?",
        "criteria": {
            "productive": "Each step changes something or learns something new",
            "stuck": "The same actions repeat without new information or progress",
            "done": "The task appears complete and the model has stopped",
        },
    },
    "model_misroute": {
        "type": "noul",
        "instructions": "Given `session.model` and the nature of `recent_tool_calls_oldest_first` and `last_user_prompt`: is an expensive frontier model (opus/fable) being used for purely mechanical work that a small model could do (bulk renames, formatting, boilerplate, copying)?",
        "criteria": {
            "true": "The work is mechanical and repetitive and the model is a top-tier expensive one",
            "false": "The work needs judgment, or the model is already a small/cheap one",
        },
    },
}
ALL_QUESTIONS = {**LEG_QUESTIONS, **COST_QUESTIONS}


# How each truth label maps onto an answer for scoring.
def score_answers(truth, answers):
    """Return {question: (predicted, expected, correct)} for every truth key that has an answer."""
    out = {}
    for k, expected in truth.items():
        if k in ("next_event", "note") or k not in answers:
            continue
        a = answers[k]
        if a["type"] == "noul":
            pred = a["p_yes"] >= 0.5
            out[k] = (round(a["p_yes"], 2), expected, pred == bool(expected))
        elif a["type"] == "choice":
            out[k] = (a["choice"], expected, a["choice"] == expected)
    return out
