Welcome to my Ollama project. This Readme is a living technical design document outlining each script's functionality.
# Main Files
Run CMD is a modern batch file designed to run commands for the Windows NT Command Processor. It determines directories for the run path, python installation path and venv path, and executes python with the "run" python script, keeping the console open.
# Shared Files
Shared packages: jsn socket subprocess sys time speech_recognition

    Json is for manipulating the settings file.

    Plyer is a third party library for toaster notifications.

    Requests is a third party library that handles HTTP POST requests to the Ollama API.

    Socket creates a singleton pattern and checks for an internet connection.

    Speech Recognition is used to "interrupt" the program from speaking and resume converting speech into text. [OPTIONAL] (See Mute in Settings)

    Subprocess sends the input text to calculate LLM output, including running piper to output TTS.

    Sys is a default package for exiting the program.

    Time is a unique feature implemented for debugginng execution time, and delaying threads[NON-OPTIONAL]

# Python Files
Run PY is a long single-instance controller responsible for reading user input and sending it to the relevant LLM.

        Atexit cleans the network sockets when the script is closed (at exit).

        Pathlib converts paths into objects for clean, efficient path manipulation. Because everything is an object in python, paths here are global constants and are implicitly Read Only.

        Threading is for creating backgorund threads to run background checks without pausing the program.

            MSVCRT "interrupts" the program from speaking when a new prompt is submitted. [OPTIONAL]

            MSVCRT AND Speech Recognition both use queue to funnel input into a queue on interruption. [NON-OPTIONAL]
        
        Winsound gives audio feedback for task status updates. [OPTIONAL]
            
    Future improvemnts include:

        A sleek engaging UI outside of CMD.

        Automation of responses for routine check-ins and scheduled tasks.

Ollama PY sends the prompt to the right Ollama model. Using the settings and specific prompt keywords, it decides what to say and which features to activate simultaneously.

    IO forces the console into UTF-8 if emojis are produced

    OS handles path formatting

    Re searches prompts for keywords

    Multiprocessing kills subprocesses on interruption and maintains the main process with a process lock.

    Shlex (shell lexer) is only used once to parse commands from args

    Shutil ensures files exists before they are executed

    Datetime greeting messages and bypassing the LLM if a simple question is asked about the current time. 

Settings JSON is a load of settings that are easy to read and write.
    Mute is whether voice-to-text features are enabled.

    Online is whether online features are enabled, such as cloud models and searching for real-time data.

    Messages for summary is how many messages are made before it starts to condense the history into an informational summary of events. Daily summaries are then condensed as weekly summaries, which then become monthly. Since the average user is expected to use the system for under 1200 months (100 years), annual summaries would be a preference and non-mandatory.

Current issues are:

    moving the optional packages to make them truly optional

    wrapping them in try statements to prevent them crashing in new environments

    adding chat history files

    searching history for specific keywords

    portfolio management of specified files