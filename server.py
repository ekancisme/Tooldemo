from flask import Flask, request, jsonify, send_file
import sys
import os
import subprocess
import threading
import queue
import io
import tempfile
import signal # Import signal module

app = Flask(__name__)

# Dictionary để theo dõi các tiến trình đang chạy (sử dụng cho đơn giản, có thể cần phức tạp hơn cho nhiều người dùng)
running_processes = {}

# Tạo một queue để lưu output (không dùng trực tiếp cho web nữa, chỉ để log)
output_queue = queue.Queue()

def run_tool_subprocess(link, username, add_icon):
    # Sử dụng file tạm thời để bắt stdout và stderr
    stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8')
    stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8')
    stdout_filename = stdout_file.name
    stderr_filename = stderr_file.name

    try:
        # Lấy biến môi trường hiện tại
        my_env = os.environ.copy()
        # Đặt biến môi trường PYTHONIOENCODING để buộc sử dụng UTF-8 cho output
        my_env['PYTHONIOENCODING'] = 'utf-8'

        # Chạy script Python như một subprocess
        process = subprocess.Popen(
            [sys.executable, 'zLocket_Tool.py'],
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding='utf-8',
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=my_env,
            # setpgrp=True # Sử dụng setpgrp=True trên Unix để tạo process group mới
            # Trên Windows, không có setpgrp, cần dùng cách khác để kill process tree nếu cần
        )

        # Lưu trữ tiến trình đang chạy
        running_processes['zlocket_tool'] = process
        print(f"Tool subprocess started with PID: {process.pid}")

        # Gửi các input theo thứ tự tool yêu cầu:
        # 1. Link hoặc Username Locket
        # 2. Username Custom
        # 3. Kích Hoạt Random Emoji (y/n)
        # 4. Xác Nhận Chạy Tool (y/n)
        process.stdin.write(f"{link}\n")
        process.stdin.write(f"{username}\n")
        process.stdin.write(f"{'Y' if add_icon else 'N'}\n")
        process.stdin.write(f"y\n")
        process.stdin.flush()
        process.stdin.close()

        # Đợi subprocess kết thúc (tool này chạy không dừng)
        # Nếu tool kết thúc (ví dụ do lỗi), chúng ta cần xóa nó khỏi running_processes
        # Tuy nhiên, vì tool chạy không dừng, chúng ta có thể bỏ qua process.wait() ở đây
        # và xử lý việc xóa khỏi dictionary khi lệnh dừng được gọi hoặc khi server tắt.

        # Đọc nội dung từ các file tạm thời (tool có thể vẫn đang ghi vào, đọc một phần)
        # Có thể cần một cơ chế đọc file theo thời gian thực nếu muốn hiển thị output trên web
        # Hiện tại chỉ đọc sau khi gửi input và trước khi hàm kết thúc.
        # Để xem output khi tool đang chạy, xem console của server.
        stdout_file.seek(0) # Quay về đầu file
        stdout_output = stdout_file.read()

        stderr_file.seek(0) # Quay về đầu file
        stderr_output = stderr_file.read()

        # Log output và error ra console của server
        print("--- Tool Stdout (after initial inputs) ---")
        print(stdout_output)
        print("--- Tool Stderr (after initial inputs) ---")
        print(stderr_output)
        print("------------------------------------------")

    except Exception as e:
        print(f"Error running tool subprocess: {e}")
        # Nếu có lỗi khi khởi chạy, xóa khỏi running_processes
        if 'zlocket_tool' in running_processes:
            del running_processes['zlocket_tool']
    finally:
        # Đóng file handle, nhưng không xóa file ở đây vì tool có thể vẫn đang ghi
        # Xóa file sẽ được xử lý khi server tắt hoặc process kết thúc (nếu có).
        stdout_file.close()
        stderr_file.close()

# Route để dừng tool
@app.route('/stop_tool', methods=['POST'])
def stop_tool_endpoint():
    global running_processes
    if 'zlocket_tool' in running_processes:
        process = running_processes['zlocket_tool']
        try:
            # Thử terminate trước (SIGTERM)
            process.terminate()
            # Hoặc kill (SIGKILL) nếu terminate không hoạt động
            # process.kill()
            print(f"Attempted to stop tool subprocess with PID: {process.pid}")

            # Đợi một chút để process kết thúc
            # process.wait(timeout=5) # Có thể đợi có timeout

            del running_processes['zlocket_tool']
            # Xóa file tạm thời sau khi process dừng
            # Cần tìm cách lấy lại tên file hoặc lưu trữ nó cùng process
            # Hiện tại, file tạm thời có thể cần xóa thủ công nếu process không kết thúc sạch sẽ.

            return jsonify({'status': f'Tool with PID {process.pid} stopped.'})
        except ProcessLookupError:
            # Process có thể đã kết thúc rồi
            del running_processes['zlocket_tool']
            return jsonify({'status': 'Tool process not found (already stopped?)'}), 404
        except Exception as e:
            return jsonify({'status': f'Error stopping tool: {e}'}), 500
    else:
        return jsonify({'status': 'No tool process is currently running.'}), 404

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/run_tool', methods=['POST'])
def run_tool_endpoint():
    global running_processes
    # Kiểm tra nếu đã có tool đang chạy
    if 'zlocket_tool' in running_processes and running_processes['zlocket_tool'].poll() is None:
         return jsonify({'status': 'Error: A tool process is already running.'}), 409

    data = request.json
    link = data.get('link')
    username = data.get('username')
    add_icon = data.get('addIcon')

    if not link or not username:
        return jsonify({'status': 'Error: Missing link or username.'}), 400

    # Chạy tool trong thread riêng
    thread = threading.Thread(target=run_tool_subprocess, args=(link, username, add_icon))
    thread.start()

    return jsonify({'status': 'Tool started running in the background. Check server console for output.'})

if __name__ == '__main__':
    # Đảm bảo file index.html tồn tại
    if not os.path.exists('index.html'):
        print("Error: index.html not found!")
        sys.exit(1)

    # Thêm xử lý khi server tắt để cố gắng dừng tool và dọn dẹp file tạm thời
    import atexit
    def cleanup():
        global running_processes
        print("Server shutting down. Attempting to stop tool process...")
        if 'zlocket_tool' in running_processes and running_processes['zlocket_tool'].poll() is None:
            process = running_processes['zlocket_tool']
            try:
                process.terminate()
                # process.kill()
                print(f"Attempted to terminate process {process.pid}")
                # Đợi một chút để tool kết thúc sau khi nhận tín hiệu
                process.wait(timeout=5)
            except Exception as e:
                print(f"Error during cleanup: {e}")
        # Có thể thêm logic tìm và xóa file tạm thời ở đây nếu cần

    atexit.register(cleanup)

    app.run(debug=True, port=5000) 