from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import time
import uuid
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# --- CẤU HÌNH SEPAY (DEMO) ---
# Trong thực tế, bạn nên để các thông tin này trong biến môi trường (Environment Variables) trên Render
SEPAY_BANK_ACCOUNT = "0345633460"  # Số tài khoản nhận tiền
SEPAY_BANK_NAME = "MBBank"         # Tên ngân hàng (MBBank)
SEPAY_API_KEY = "my_secret_sepay_token" # Token bảo mật webhook SePay (cấu hình bên SePay)

# Giả lập database (Trong thực tế nên dùng PostgreSQL hoặc MongoDB)
orders_db = {}

# --- CÁC API CHÍNH ---
@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "message": "API Thanh toán (SePay Integration) đang chạy!",
        "timestamp": datetime.now().isoformat()
    })

# 1. API TẠO ĐƠN HÀNG & LẤY LINK THANH TOÁN
@app.route('/api/payment/create', methods=['POST'])
def create_payment():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        # Lấy dữ liệu từ request
        customer_name = data.get('customer_name', 'Khách lẻ')
        kingdom = data.get('kingdom', 'Default Kingdom')
        order_details = data.get('order_details', []) # Danh sách món hàng
        amount = data.get('amount', 0)
        
        # Xử lý ngày tạo
        created_date = data.get('created_date')
        if not created_date:
            created_date = datetime.now().isoformat()

        if not amount or amount <= 0:
            return jsonify({"error": "Số tiền không hợp lệ"}), 400

        # Tạo Mã Đơn Hàng (Order Code) ngắn gọn để dùng làm nội dung chuyển khoản
        # Lưu ý: Nội dung CK nên ngắn gọn và KHÔNG DẤU. Ví dụ: DH17019283
        timestamp_code = int(time.time())
        order_code = f"DH{timestamp_code}"
        
        # Lưu đơn hàng vào DB
        orders_db[order_code] = {
            "order_code": order_code,
            "customer_name": customer_name,
            "kingdom": kingdom,
            "order_details": order_details,
            "amount": amount,
            "status": "pending", # Trạng thái chờ thanh toán
            "created_at": created_date,
            "payment_method": "bank_transfer"
        }
        
        # Tạo link QR Code thanh toán (Sử dụng API tạo QR nhanh của SePay)
        # Cấu trúc: https://qr.sepay.vn/img?acc={STK}&bank={Bank}&amount={Tien}&des={NoiDung}
        payment_url = (
            f"https://qr.sepay.vn/img?"
            f"acc={SEPAY_BANK_ACCOUNT}"
            f"&bank={SEPAY_BANK_NAME}"
            f"&amount={amount}"
            f"&des={order_code}"
            f"&template=compact" 
        )

        return jsonify({
            "success": True,
            "order_code": order_code,
            "amount": amount,
            "message": "Tạo đơn hàng thành công",
            "payment_url": payment_url, # Link ảnh QR Code để hiển thị cho khách
            "qr_data": {
                "account": SEPAY_BANK_ACCOUNT,
                "bank": SEPAY_BANK_NAME,
                "amount": amount,
                "content": order_code
            }
        })
    except Exception as e:
        print(f"Error creating payment: {e}")
        return jsonify({"error": str(e)}), 500

# 2. API WEBHOOK (NHẬN DỮ LIỆU TỪ SEPAY)
@app.route('/api/sepay/webhook', methods=['POST'])
def sepay_webhook():
    # SePay sẽ gọi vào đây khi có giao dịch ngân hàng
    data = request.json
    
    # Log dữ liệu nhận được để debug trên Render Dashboard
    print(f"Webhook received: {data}")
    
    if not data:
        return jsonify({"error": "No data"}), 400

    # Cấu trúc dữ liệu SePay gửi:
    # {
    #   "gateway": "MBBank",
    #   "transactionDate": "...",
    #   "accountNumber": "...",
    #   "content": "DH170123456",
    #   "transferType": "in",
    #   "transferAmount": 50000,
    #   ...
    # }

    # 1. Lấy nội dung chuyển khoản
    transfer_code = data.get('code', '') 
    transfer_amount = data.get('transferAmount', 0)
    
    # 2. Tìm đơn hàng tương ứng trong DB
    found_order = None
    for code, order in orders_db.items():

        if code in transfer_code:
            found_order = order
            break
            
    if not found_order:

        print(f"Không tìm thấy đơn hàng cho giao dịch: {transfer_code}")
        return jsonify({"success": False, "message": "Order not found"}), 200

    # 3. Kiểm tra số tiền (Cho phép sai số nhỏ nếu cần, ở đây check chính xác hoặc lớn hơn)
    if transfer_amount < found_order['amount']:
        print(f"Số tiền không đủ. Yêu cầu: {found_order['amount']}, Nhận: {transfer_amount}")
        return jsonify({"success": False, "message": "Insufficient amount"}), 200

    # 4. Cập nhật trạng thái đơn hàng
    if found_order['status'] != 'paid':
        found_order['status'] = 'paid'
        found_order['paid_at'] = datetime.now().isoformat()
        found_order['transaction_ref'] = data.get('referenceCode', 'N/A')
        print(f"ĐƠN HÀNG THÀNH CÔNG: {found_order['order_code']}")

    return jsonify({
        "success": True, 
        "message": "Payment updated successfully",
        "order_code": found_order['order_code']
    })

# 3. API KIỂM TRA TRẠNG THÁI ĐƠN (Dành cho Frontend polling)
@app.route('/api/order/<order_code>', methods=['GET'])
def get_order_status(order_code):
    order = orders_db.get(order_code)
    if not order:
        return jsonify({"error": "Không tìm thấy đơn hàng"}), 404
    return jsonify(order)

# --- ENDPOINT TEST WEBHOOK (DÙNG ĐỂ TỰ TEST NẾU KHÔNG CÓ SEPAY THẬT) ---
@app.route('/api/test/simulate-payment', methods=['POST'])
def simulate_payment():
    data = request.json
    order_code = data.get('order_code')
    
    order = orders_db.get(order_code)
    if not order:
        return jsonify({"error": "Order not found"}), 404
        
    # Giả lập payload giống SePay gửi sang
    fake_sepay_payload = {
        "gateway": "MBBank",
        "transactionDate": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "accountNumber": SEPAY_BANK_ACCOUNT,
        "content": f"{order_code} ck mua hang", 
        "transferType": "in",
        "transferAmount": order['amount'],
        "referenceCode": f"FT{int(time.time())}"
    }
    
    # Gọi nội bộ hàm xử lý webhook
    with app.test_request_context('/api/sepay/webhook', 
                                  method='POST', 
                                  json=fake_sepay_payload,
                                  headers={'Content-Type': 'application/json'}):
        response = sepay_webhook()
        return response

if __name__ == '__main__':
    # Chạy local
    app.run(debug=True, port=5000)