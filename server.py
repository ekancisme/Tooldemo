from flask import Flask, request, jsonify, send_file
import sys
import os
import subprocess
import threading
import queue
import io
import tempfile
import signal
import datetime
import json

app = Flask(__name__)

# Dictionary to track running processes with more information
running_processes = {}

# Queue for output (not used directly for web anymore, just for logging)
output_queue = queue.Queue()

def auto_kill_process(pid):
    """Automatically kill a process after timeout"""
    if pid in running_processes:
        process_info = running_processes[pid]
        process = process_info['process']
        
        # Check if process is still running
        if process.poll() is None:
            try:
                process.terminate()
                print(f"Auto-stopped process PID {pid} after timeout")
                
                # Clean up temporary files
                try:
                    os.unlink(process_info['stdout_file'])
                    os.unlink(process_info['stderr_file'])
                except Exception as e:
                    print(f"Error cleaning up temporary files for process {pid}: {e}")
                
                # Remove from running processes
                del running_processes[pid]
            except Exception as e:
                print(f"Error auto-stopping process {pid}: {e}")

def run_tool_subprocess(link, username, add_icon):
    # Use temporary files to capture stdout and stderr
    stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8')
    stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8')
    stdout_filename = stdout_file.name
    stderr_filename = stderr_file.name

    try:
        # Get current environment variables
        my_env = os.environ.copy()
        # Set PYTHONIOENCODING to force UTF-8 for output
        my_env['PYTHONIOENCODING'] = 'utf-8'

        # Run Python script as subprocess
        process = subprocess.Popen(
            [sys.executable, 'zLocket_Tool.py'],
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding='utf-8',
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=my_env,
        )

        # Store process information
        process_info = {
            'process': process,
            'pid': process.pid,
            'username': username,
            'link': link,
            'start_time': datetime.datetime.now().isoformat(),
            'stdout_file': stdout_filename,
            'stderr_file': stderr_filename
        }
        
        running_processes[process.pid] = process_info
        print(f"Tool subprocess started with PID: {process.pid}")

        # Create a timer to automatically stop the process after 1 minute
        timer = threading.Timer(60.0, auto_kill_process, args=[process.pid])
        timer.daemon = True  # Make sure timer thread doesn't prevent program exit
        timer.start()

        # Send inputs in order:
        # 1. Link or Username Locket
        # 2. Username Custom
        # 3. Activate Random Emoji (y/n)
        # 4. Confirm Run Tool (y/n)
        process.stdin.write(f"{link}\n")
        process.stdin.write(f"{username}\n")
        process.stdin.write(f"{'Y' if add_icon else 'N'}\n")
        process.stdin.write(f"y\n")
        process.stdin.flush()
        process.stdin.close()

        # Read initial output
        stdout_file.seek(0)
        stdout_output = stdout_file.read()
        stderr_file.seek(0)
        stderr_output = stderr_file.read()

        # Log output and error to server console
        print("--- Tool Stdout (after initial inputs) ---")
        print(stdout_output)
        print("--- Tool Stderr (after initial inputs) ---")
        print(stderr_output)
        print("------------------------------------------")

    except Exception as e:
        print(f"Error running tool subprocess: {e}")
        # If error occurs during startup, remove from running_processes
        if process.pid in running_processes:
            del running_processes[process.pid]
    finally:
        # Close file handles but don't delete files yet
        stdout_file.close()
        stderr_file.close()

@app.route('/admin/processes', methods=['GET'])
def get_processes():
    # Return list of running processes
    processes = []
    for pid, info in running_processes.items():
        if info['process'].poll() is None:  # Process is still running
            processes.append({
                'pid': pid,
                'username': info['username'],
                'link': info['link'],
                'start_time': info['start_time']
            })
        else:
            # Process has ended, clean up
            del running_processes[pid]
    
    return jsonify({'processes': processes})

@app.route('/admin/stop', methods=['POST'])
def stop_process():
    data = request.json
    pid = data.get('pid')
    
    if not pid or pid not in running_processes:
        return jsonify({'status': 'Process not found'}), 404
    
    process_info = running_processes[pid]
    process = process_info['process']
    
    try:
        # Try terminate first (SIGTERM)
        process.terminate()
        print(f"Attempted to stop tool subprocess with PID: {pid}")
        
        # Clean up temporary files
        try:
            os.unlink(process_info['stdout_file'])
            os.unlink(process_info['stderr_file'])
        except Exception as e:
            print(f"Error cleaning up temporary files: {e}")
        
        del running_processes[pid]
        return jsonify({'status': f'Process {pid} stopped successfully'})
    except Exception as e:
        return jsonify({'status': f'Error stopping process: {str(e)}'}), 500

@app.route('/admin')
def admin_panel():
    return send_file('admin.html')

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/run_tool', methods=['POST'])
def run_tool_endpoint():
    data = request.json
    link = data.get('link')
    username = data.get('username')
    add_icon = data.get('addIcon')

    if not link or not username:
        return jsonify({'status': 'Error: Missing link or username.'}), 400

    # Run tool in separate thread
    thread = threading.Thread(target=run_tool_subprocess, args=(link, username, add_icon))
    thread.start()

    # Wait a moment to get the PID
    thread.join(timeout=1)
    
    # Find the most recently added process
    latest_pid = None
    latest_time = None
    for pid, info in running_processes.items():
        if latest_time is None or info['start_time'] > latest_time:
            latest_pid = pid
            latest_time = info['start_time']

    return jsonify({
        'status': 'Tool started running in the background. Will auto-stop after 1 minute.',
        'pid': latest_pid
    })

@app.route('/stop_tool', methods=['POST'])
def stop_tool_endpoint():
    data = request.json
    pid = data.get('pid')
    
    if not pid or pid not in running_processes:
        return jsonify({'status': 'Process not found'}), 404
    
    process_info = running_processes[pid]
    process = process_info['process']
    
    try:
        process.terminate()
        print(f"Attempted to stop tool subprocess with PID: {pid}")
        
        # Clean up temporary files
        try:
            os.unlink(process_info['stdout_file'])
            os.unlink(process_info['stderr_file'])
        except Exception as e:
            print(f"Error cleaning up temporary files: {e}")
        
        del running_processes[pid]
        return jsonify({'status': f'Process {pid} stopped successfully'})
    except Exception as e:
        return jsonify({'status': f'Error stopping process: {str(e)}'}), 500

if __name__ == '__main__':
    # Ensure index.html exists
    if not os.path.exists('index.html'):
        print("Error: index.html not found!")
        sys.exit(1)

    # Add cleanup handler when server shuts down
    import atexit
    def cleanup():
        print("Server shutting down. Attempting to stop all processes...")
        for pid, process_info in list(running_processes.items()):
            try:
                process = process_info['process']
                if process.poll() is None:
                    process.terminate()
                    print(f"Attempted to terminate process {pid}")
                    process.wait(timeout=5)
                
                # Clean up temporary files
                try:
                    os.unlink(process_info['stdout_file'])
                    os.unlink(process_info['stderr_file'])
                except Exception as e:
                    print(f"Error cleaning up temporary files for process {pid}: {e}")
            except Exception as e:
                print(f"Error during cleanup for process {pid}: {e}")

    atexit.register(cleanup)

    app.run(host='0.0.0.0', port=5000) 