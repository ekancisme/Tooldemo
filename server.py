from flask import Flask, request, jsonify, send_file
import sys
import os
import subprocess
import threading
import queue
import io
import tempfile # Import tempfile

app = Flask(__name__)

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
        # Chuyển hướng stdout và stderr đến các file tạm thời
        # Truyền biến môi trường đã sửa đổi
        process = subprocess.Popen(
            [sys.executable, 'zLocket_Tool.py'],
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True, # Sử dụng text mode cho input/output (string)
            encoding='utf-8', # Quan trọng: Sử dụng UTF-8 cho stdin
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=my_env # Truyền biến môi trường
        )

        # Gửi các input theo thứ tự tool yêu cầu:
        # 1. Link hoặc Username Locket
        # 2. Username Custom
        # 3. Kích Hoạt Random Emoji (y/n)
        # 4. Xác Nhận Chạy Tool (y/n)
        process.stdin.write(f"{link}\n")
        process.stdin.write(f"{username}\n")
        process.stdin.write(f"{'Y' if add_icon else 'N'}\n")
        process.stdin.write(f"y\n") # Thêm input xác nhận chạy tool
        process.stdin.flush()
        process.stdin.close() # Đóng stdin sau khi gửi hết input

        # Đợi subprocess kết thúc (tool này chạy không dừng, nên có thể không kết thúc trừ khi lỗi)
        # process.wait()
        # Có thể tool sẽ chạy mãi, nên chúng ta sẽ không đợi ở đây. Output sẽ ghi vào file tạm thời.
        # Bạn sẽ cần dừng server hoặc process thủ công để dừng tool.

        # Đọc nội dung từ các file tạm thời (có thể chỉ đọc một phần nếu tool chạy lâu)
        stdout_file.seek(0) # Quay về đầu file
        stdout_output = stdout_file.read()

        stderr_file.seek(0) # Quay về đầu file
        stderr_output = stderr_file.read()

        # Log output và error ra console của server
        print("--- Tool Stdout ---")
        print(stdout_output)
        print("--- Tool Stderr ---")
        print(stderr_output)
        print("-------------------")

    except Exception as e:
        print(f"Error running tool subprocess: {e}")
    finally:
        # Đóng và dọn dẹp các file tạm thời (thực hiện sau khi process kết thúc hoặc bị dừng)
        # Trong trường hợp tool chạy không dừng, các file này có thể không bị xóa tự động.
        # Bạn có thể cần xóa thủ công sau khi dừng server/tool.
        stdout_file.close()
        stderr_file.close()
        # Các dòng xóa file tạm thời có thể gây lỗi nếu file vẫn đang được ghi bởi subprocess
        # if os.path.exists(stdout_filename):
        #     os.remove(stdout_filename)
        # if os.path.exists(stderr_filename):
        #     os.remove(stderr_filename)

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

    # Chạy tool trong thread riêng để không chặn server
    thread = threading.Thread(target=run_tool_subprocess, args=(link, username, add_icon))
    thread.start()

    return jsonify({'status': 'Tool started running in the background. Check server console for output.'})

if __name__ == '__main__':
    # Đảm bảo file index.html tồn tại
    if not os.path.exists('index.html'):
        print("Error: index.html not found!")
        sys.exit(1)

    app.run(debug=True, port=5000) 