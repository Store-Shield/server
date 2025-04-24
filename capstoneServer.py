from flask import Flask, request, jsonify, render_template
import base64
import cv2
import numpy as np
import os
from flask_socketio import SocketIO, emit
import threading
from flask_sqlalchemy import SQLAlchemy
from flask import send_file  # 이 라인이 파일 상단에 있어야 합니다
import json
from datetime import datetime, date
import time
from sqlalchemy import func, and_, or_
from datetime import datetime, date, timedelta

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
# 전역 변수로 이미지 저장
current_image = None
base64_image = None


# 영상 저장을 위한 변수 추가
recording_active = False
frame_buffer = []  # 프레임과 타임스탬프 저장
active_persons = set()





# 영상 저장 함수 정의
def save_person_video(person_id):
    if not frame_buffer:
        print(f"{person_id}에 대한 프레임 없음")
        return

    folder = 'videos'
    os.makedirs(folder, exist_ok=True)
    filename = f"{folder}/person_{person_id}.mp4"

    height, width, _ = frame_buffer[0]['image'].shape
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filename, fourcc, 15.0, (width, height))

    for item in frame_buffer:
        out.write(item['image'])

    out.release()
    print(f"{person_id}에 대한 영상 저장 완료: {filename}")

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:csedbadmin@localhost/cctv_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 키오스크 위치 정보 저장
kiosk_request_pending = False
kiosk_waiting_client = None

# 테이블 모델 정의
class Customer(db.Model):
    __tablename__ = 'customer'
    
    customer_id = db.Column(db.Integer, primary_key=True)
    come_in = db.Column(db.DateTime)
    come_out = db.Column(db.DateTime)
    cal_state = db.Column(db.String(20))
    customer_image = db.Column(db.Text)
    video_thumbnail = db.Column(db.Text(length=4294967295)) 
    
    carts = db.relationship('Cart', backref='customer', lazy=True,
                           cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'customer_id': self.customer_id,
            'come_in': self.come_in.strftime('%Y-%m-%d %H:%M:%S') if self.come_in else None,
            'come_out': self.come_out.strftime('%Y-%m-%d %H:%M:%S') if self.come_out else None,
            'cal_state': self.cal_state,
            'customer_image': self.customer_image,
            'video_thumbnail': self.video_thumbnail
        }

class Cart(db.Model):
    __tablename__ = 'cart'
    
    cart_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.customer_id', ondelete='CASCADE'), nullable=False)
    total_price = db.Column(db.Float)
    
    cart_items = db.relationship('CartItems', backref='cart', lazy=True,
                                cascade="all, delete-orphan")
    payments = db.relationship('Payment', backref='cart', lazy=True,
                              cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'cart_id': self.cart_id,
            'customer_id': self.customer_id,
            'total_price': self.total_price
        }

class CartItems(db.Model):
    __tablename__ = 'cart_items'
    
    auto_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('cart.cart_id', ondelete='CASCADE'), nullable=False)
    product_name = db.Column(db.String(100), db.ForeignKey('product.product_name', ondelete='CASCADE'), nullable=False)

class Payment(db.Model):
    __tablename__ = 'payment'
    
    pay_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pay_time = db.Column(db.DateTime)
    cart_id = db.Column(db.Integer, db.ForeignKey('cart.cart_id', ondelete='CASCADE'), nullable=False)

class Product(db.Model):
    __tablename__ = 'product'
    
    product_name = db.Column(db.String(100), primary_key=True)
    product_price = db.Column(db.Float, nullable=False)
    product_image = db.Column(db.Text)
    product_stock = db.Column(db.Integer)
    
    cart_items = db.relationship('CartItems', backref='product', lazy=True,
                                cascade="all, delete-orphan")
    year_sales = db.relationship('YearSales', backref='product', lazy=True,
                                cascade="all, delete-orphan")
    month_sales = db.relationship('MonthSales', backref='product', lazy=True,
                                 cascade="all, delete-orphan")
    day_sales = db.relationship('DaySales', backref='product', lazy=True,
                               cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'product_name': self.product_name,
            'product_price': self.product_price,
            'product_image': self.product_image,
            'product_stock': self.product_stock
        }

class YearSales(db.Model):
    __tablename__ = 'year_sales'
    
    year = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(100), db.ForeignKey('product.product_name', ondelete='CASCADE'), primary_key=True)
    count = db.Column(db.Integer)

class MonthSales(db.Model):
    __tablename__ = 'month_sales'
    
    month = db.Column(db.String(7), primary_key=True)
    product_name = db.Column(db.String(100), db.ForeignKey('product.product_name', ondelete='CASCADE'), primary_key=True)
    count = db.Column(db.Integer)

class DaySales(db.Model):
    __tablename__ = 'day_sales'
    
    day = db.Column(db.String(10), primary_key=True)
    product_name = db.Column(db.String(100), db.ForeignKey('product.product_name', ondelete='CASCADE'), primary_key=True)
    count = db.Column(db.Integer)

def update_window():
    global current_image
    while True:
        if current_image is not None:
            cv2.imshow("Received Image", current_image)
            cv2.waitKey(1)

# 오늘 날짜의 고객만 가져오는 함수
def get_todays_customers():
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    return Customer.query.filter(
        and_(
            Customer.come_in >= today_start,
            Customer.come_in <= today_end
        )
    ).all()

# 카트에 담긴 제품 정보 가져오기
def get_cart_items(cart_id):
    # 카트에 담긴 제품을 product_name으로 그룹화하고 개수 계산
    cart_items_grouped = db.session.query(
        CartItems.product_name, 
        func.count(CartItems.product_name).label('count')
    ).filter(
        CartItems.cart_id == cart_id
    ).group_by(
        CartItems.product_name
    ).all()
    
    # 제품 정보와 함께 반환
    result = []
    for product_name, count in cart_items_grouped:
        product = Product.query.filter_by(product_name=product_name).first()
        if product:
            result.append({
                'product_name': product_name,
                'count': count,
                'price': product.product_price,
                'product_image': product.product_image,
                'subtotal': product.product_price * count
            })
    
    return result

# 고객 정보와 카트 정보를 함께 가져오는 함수
def get_customer_with_cart_info(customer_id):
    customer = Customer.query.filter_by(customer_id=customer_id).first()
    if not customer:
        return None
    
    # 고객 기본 정보
    customer_info = customer.to_dict()
    
    # 카트 정보 가져오기
    cart = Cart.query.filter_by(customer_id=customer_id).first()
    if cart:
        # 카트에 담긴 제품 정보
        customer_info['cart'] = cart.to_dict()
        customer_info['cart_items'] = get_cart_items(cart.cart_id)
        customer_info['has_items'] = len(customer_info['cart_items']) > 0
    else:
        customer_info['cart'] = None
        customer_info['cart_items'] = []
        customer_info['has_items'] = False
    
    return customer_info

# 고객 데이터 업데이트를 클라이언트에 보내는 함수
def send_customer_update():
    todays_customers = get_todays_customers()
    customer_data = []
    for customer in todays_customers:
        customer_info = get_customer_with_cart_info(customer.customer_id)
        if customer_info:
            customer_data.append(customer_info)
    
    emit('customer_update', {'customers': customer_data} ,broadcast=True)

@app.route('/')
@app.route('/show')
def show():
    # 오늘 날짜의 고객만 가져오기
    todays_customers = get_todays_customers()
    
    # 각 고객의 카트 및 제품 정보를 함께 가져오기
    customers_data = []
    for customer in todays_customers:
        customer_info = get_customer_with_cart_info(customer.customer_id)
        if customer_info:
            customers_data.append(customer_info)
    
    return render_template('real_time_cctv_analysis.html', customers=customers_data)

@app.route('/kiosk')
def kiosk():
    return render_template('kiosk.html')

# 웹소켓 연결 이벤트
@socketio.on('connect')
def handle_connect():
    print('클라이언트 연결됨')

@socketio.on('findPersonFace')
def handle_find_person_face(data):
    faces_data = data.get('faces', {})
    
    # 문자열 키를 정수로 변환하여 딕셔너리 생성
    faces = {int(key): value for key, value in faces_data.items()}
    
    # 각 사람 ID와 이미지 데이터에 접근
    for person_id, image_data in faces.items():
        print(f"사람 ID: {person_id}")
        
        try:
            # 기존 고객 찾기
            customer = Customer.query.filter_by(customer_id=person_id).first()
            if customer:
                # 고객 이미지 업데이트
                customer.customer_image = image_data
                db.session.commit()
                print(f"고객 ID {person_id}의 이미지 업데이트 완료")
                
                # 고객 데이터 업데이트 전송
                send_customer_update()
            
            # 이미지 표시 (디버깅용)
            image_binary = base64.b64decode(image_data)
            nparr = np.frombuffer(image_binary, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            window_name = f"Person ID: {person_id}"
            resized_image = cv2.resize(image, (500, 500))
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            cv2.imshow(window_name, resized_image)
            cv2.waitKey(1)
            
            print(f"사람 ID {person_id}의 이미지 처리 완료")
        except Exception as e:
            print(f"이미지 처리 오류: {str(e)}")


# 키오스크에서 가장 가까운 고객 요청
@socketio.on('request_nearest_customer')
def handle_nearest_customer_request(data):
    global kiosk_request_pending, kiosk_waiting_client
    try:
        kiosk_id = data.get('kioskId')
        print(f"키오스크 {kiosk_id}에서 가장 가까운 고객 요청")
        
        # 요청 상태 설정
        kiosk_request_pending = True
        kiosk_waiting_client = request.sid
        
        # 앱에 키오스크 위치 근처의 고객 요청
        emit('find_nearest_person', {'kioskId': kiosk_id}, broadcast=True)
        
    except Exception as e:
        print(f"가장 가까운 고객 요청 처리 오류: {str(e)}")
        emit('customer_info', {'success': False, 'error': str(e)})

# 앱에서 가장 가까운 고객 ID 수신
@socketio.on('nearest_person_found')
def handle_nearest_person(data):
    global kiosk_request_pending, kiosk_waiting_client
    try:
        if kiosk_request_pending and kiosk_waiting_client:
            person_id = data.get('personId')
            
            if person_id:
                # 고객 정보 및 카트 정보 조회
                customer_info = get_customer_with_cart_info(person_id)
                
                if customer_info:
                    if not customer_info['has_items']:
                        # 장바구니에 담긴 제품이 없는 경우
                        emit('customer_info', {
                            'success': 0,
                            'customer': customer_info
                        }, to=kiosk_waiting_client)
                    else:
                        # 고객 상태를 결제중으로 변경
                        customer = Customer.query.filter_by(customer_id=person_id).first()
                        if customer and customer.cal_state == '결제대기':
                            customer.cal_state = '결제중'
                            db.session.commit()
                            # 변경된 정보로 고객 정보 업데이트
                            customer_info = get_customer_with_cart_info(person_id)
                            
                            # 고객 데이터 업데이트 전송
                            send_customer_update()

                        # 키오스크에 고객 정보 전송
                        emit('customer_info', {
                            'success': 1,
                            'customer': customer_info
                        }, to=kiosk_waiting_client)
                else:
                    # 고객 정보가 없을 경우
                    emit('customer_info', {
                        'success': -1,
                        'error': '고객 정보를 찾을 수 없습니다.'
                    }, to=kiosk_waiting_client)
            else:
                # 가까운 고객이 없을 경우
                emit('customer_info', {
                    'success': False,
                    'error': '가까운 고객을 찾을 수 없습니다.'
                }, to=kiosk_waiting_client)
            
            # 요청 상태 초기화
            kiosk_request_pending = False
            kiosk_waiting_client = None
            
    except Exception as e:
        print(f"가장 가까운 고객 처리 오류: {str(e)}")
        if kiosk_waiting_client:
            emit('customer_info', {'success': False, 'error': str(e)}, to=kiosk_waiting_client)
        kiosk_request_pending = False
        kiosk_waiting_client = None

# 결제 확인 처리
@socketio.on('confirm_payment')
def handle_payment_confirmation(data):
    try:
        customer_id = data.get('customerId')
        
        if customer_id:
            # 해당 고객의 DB 정보 조회
            customer = Customer.query.filter_by(customer_id=customer_id).first()
            
            if customer:
                # 고객 상태를 결제완료로 변경
                customer.cal_state = '결제완료'
                db.session.commit()
                
                # 결제 테이블에 결제 정보 추가
                cart = Cart.query.filter_by(customer_id=customer_id).first()
                if cart:
                    new_payment = Payment(
                        pay_time=datetime.now(),
                        cart_id=cart.cart_id
                    )
                    db.session.add(new_payment)
                    db.session.commit()
                
                # 결제 완료 응답
                emit('payment_completed', {'success': True})
                
                # 고객 데이터 업데이트 전송
                send_customer_update()
            else:
                emit('payment_completed', {
                    'success': False,
                    'error': '고객 정보를 찾을 수 없습니다.'
                })
        else:
            emit('payment_completed', {
                'success': False,
                'error': '고객 ID가 제공되지 않았습니다.'
            })
            
    except Exception as e:
        print(f"결제 확인 처리 오류: {str(e)}")
        emit('payment_completed', {'success': False, 'error': str(e)})

# 웹소켓 메시지 수신
@socketio.on('message')
def handle_message(message):
    global current_image
    global base64_image
    
    try:
        # JSON 문자열 파싱
        import json
        data = json.loads(message)

        if data.get('type') == 'image':
            base64_image = data.get('image')
            emit('image_update', {'image': base64_image}, broadcast=True)
 
            if not base64_image:
                return

            # Base64 디코딩 및 이미지 변환
            image_data = base64.b64decode(base64_image)
            nparr = np.frombuffer(image_data, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if image is None:
                print("이미지 디코딩 실패")
                return

            # 프레임 저장 로직
            global recording_active, frame_buffer, active_persons
            timestamp = data.get('timestamp', int(time.time() * 1000))

            if recording_active:
                frame_buffer.append({"timestamp": timestamp, "image": image})
                print(f"프레임 저장됨 ({len(frame_buffer)}개 누적)")

            # 이미지 처리
            resized_image = cv2.resize(image, (800, 700))
            current_image = resized_image

            # 클라이언트에 응답
            emit('response', {'status': 'success'})
            
        elif data.get('type') == 'personAppearance':
        
            timestamp_ms = data.get('timestamp')
            thumbnail=data.get('thumbnail')
            personIds = data.get('personIds')
            
            # 밀리초 타임스탬프를 DateTime으로 변환
            datetime_obj = datetime.fromtimestamp(timestamp_ms / 1000.0)
            
            print(f"{datetime_obj} 시간에 {personIds} 등장")

            # 영상 버퍼 관리
            active_persons.update(personIds)
            if not recording_active:
                print("버퍼 담기 시작")
                recording_active = True
                frame_buffer = []

            # 각 사람 ID에 대한 처리
            for person_id in personIds:
                # 기존에 등록된 고객인지 확인
                existing_customer = Customer.query.filter_by(customer_id=person_id).first()
                
                if existing_customer:
                    # 기존 고객의 데이터 삭제 (테스트 환경에서의 중복 문제 해결)
                    print(f"기존에 등록된 고객 ID {person_id} 데이터 삭제")
                    
                    # Cart 먼저 삭제 (CASCADE 설정으로 CartItems, Payment도 함께 삭제됨)
                    carts = Cart.query.filter_by(customer_id=person_id).all()
                    for cart in carts:
                        db.session.delete(cart)
                    
                    # Customer 삭제
                    db.session.delete(existing_customer)
                    db.session.commit()
                
                # 새 고객 등록
                new_customer = Customer(
                    customer_id=person_id,
                    come_in=datetime_obj,
                    come_out=None,  # 퇴장 시간은 NULL로 설정
                    cal_state='결제대기',
                    customer_image=None , # 이미지는 나중에 업데이트
                    video_thumbnail=thumbnail

                )
                db.session.add(new_customer)
                
                # 고객의 장바구니 생성
                new_cart = Cart(
                    customer_id=person_id,
                    total_price=0.0
                )
                db.session.add(new_cart)
                
                db.session.commit()
                
                print(f"고객 ID {person_id} DB에 추가됨")
                send_customer_update()
            
            # 얼굴 이미지 요청
            emit('requestPersonFaceFind', {'personIds': personIds})
            print("requestPersonFaceFind 서버에서 요청")
            
         
            
        elif data.get('type') == 'personDisappearance':
            
            timestamp_ms = data.get('timestamp')
            personIds = data.get('personIds')
            
            # 밀리초 타임스탬프를 DateTime으로 변환
            datetime_obj = datetime.fromtimestamp(timestamp_ms / 1000.0)
            
            print(f"{datetime_obj} 시간에 {personIds} 없어짐")

            # 고객 상태 업데이트
            for person_id in personIds:
                customer = Customer.query.filter_by(customer_id=person_id).first()
                if customer:
                    # 퇴장 시간 기록
                    customer.come_out = datetime_obj
                    
                    # 카트 정보 확인
                    cart = Cart.query.filter_by(customer_id=person_id).first()
                    if cart:
                        # 카트에 제품이 있는지 확인
                        cart_items = CartItems.query.filter_by(cart_id=cart.cart_id).count()
                        has_items = cart_items > 0
                        
                        # 상품을 가지고 있고 결제 상태에 따른 처리
                        if has_items:
                            if customer.cal_state in ['결제대기', '결제중']:
                                customer.cal_state = '절도의심'
                                db.session.commit()
                                print(f"고객 ID {person_id} 절도 의심")
                                save_person_video(person_id)  # 절도 의심 영상 저장
                        elif customer.cal_state == '결제대기':
                            customer.cal_state = '일반퇴장'
                            db.session.commit()
                            print(f"고객 ID {person_id} 일반퇴장")
                    
                    db.session.commit()
            send_customer_update()
            # 영상 버퍼 관리
            active_persons.difference_update(personIds)
            if not active_persons:
                recording_active = False
                frame_buffer = []  # 전체 버퍼 초기화
                print("모든 사람이 퇴장하여 녹화 중단")
            
            
            
        elif data.get('type') == 'action':
            person_id = data.get('personId')
            product_name = data.get('object')  # cup, book, laptop 등 제품 이름
            act = data.get('act')  # 0: 내려놓음, 1: 집음
            if(product_name=="cup"):
                product_name="컵"
            elif(product_name=="banana"):
                product_name="바나나나"
            elif(product_name=="apple"):
                product_name="사과"
            # 제품이 존재하는지 확인
            product = Product.query.filter_by(product_name=product_name).first()
            if not product:
                print(f"제품 '{product_name}' 찾을 수 없음")
                return
                
            # 고객의 카트 찾기
            cart = Cart.query.filter_by(customer_id=person_id).first()
            if not cart:
                print(f"고객 ID {person_id}의 카트를 찾을 수 없음")
                return
            
            if act == 1:  # 집음
                # 새 아이템 장바구니에 추가
                new_item = CartItems(
                    cart_id=cart.cart_id,
                    product_name=product_name
                )
                db.session.add(new_item)
                
                # 카트 총액 업데이트
                cart.total_price = (cart.total_price or 0) + product.product_price
                db.session.commit()
                
                print(f"{person_id}가 {product_name}을 집었습니다")
                
            elif act == 0:  # 내려놓음
                # 장바구니에서 해당 제품 찾기
                cart_item = CartItems.query.filter_by(
                    cart_id=cart.cart_id, 
                    product_name=product_name
                ).first()
                
                if cart_item:
                    # 아이템 삭제
                    db.session.delete(cart_item)
                    
                    # 카트 총액 업데이트
                    cart.total_price = max(0, (cart.total_price or 0) - product.product_price)
                    db.session.commit()
                    
                    print(f"{person_id}가 {product_name}을 내려놓았습니다")
                else:
                    print(f"{person_id}의 장바구니에 {product_name}이 없습니다")
            
            # 고객 데이터 업데이트 전송
            send_customer_update()

    except Exception as e:
        print(f"웹소켓 처리 오류: {str(e)}")








#=========================    hyechang code ============================

@app.route('/download_video/<int:person_id>', methods=['GET'])
def download_video(person_id):
    try:
        # 영상 파일 경로
        video_path = f"videos/person_{person_id}.mp4"
        
        # 파일이 존재하는지 확인
        if os.path.exists(video_path):
            # 다운로드를 위해 파일 전송
            return send_file(video_path, 
                            mimetype='video/mp4',
                            as_attachment=True, 
                            download_name=f"suspect_{person_id}.mp4")
        else:
            return jsonify({"error": "영상 파일을 찾을 수 없습니다."}), 404
    except Exception as e:
        print(f"영상 다운로드 오류: {str(e)}")
        return jsonify({"error": f"영상 다운로드 중 오류가 발생했습니다: {str(e)}"}), 500
    





stock_lack_count=5; #서버에서 관리 현도랑 이름 맞춰야함함

# 현재 날짜의 시작과 끝 시간을 반환하는 헬퍼 함수
def get_today_range():
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    return today_start, today_end

# 테스트를 위한!!!! 2024년의 특정 날짜를 사용
def get_fixed_date_range():
    fixed_date = datetime(2023, 12, 31).date()
    day_start = datetime.combine(fixed_date, datetime.min.time())
    day_end = datetime.combine(fixed_date, datetime.max.time())
    return day_start, day_end  # 2개 반환
# 플러터 앱의 페이지 로드 요청 처리
@socketio.on('hyechangPageload')
def handle_hyechang_pageload(data):
    try:
        page_type = data.get('pageType')
        
        if page_type == "mainPage":
            # 메인 페이지 데이터 로드
            handle_main_page_data()
        elif page_type == "alertPage":
            # 알림 페이지 데이터 로드 (연도별 용의자 및 재고 알림)
            
            year = data.get('year', datetime.now().year)  # 요청된 연도 또는 현재 연도
            print(year,end=" ")
            print("년도 절도 요청")
             # 재고 부족 기준 (기본값 5) 서버에서 관리
            handle_alert_page_data(year, stock_lack_count)
    except Exception as e:
        print(f"페이지 데이터 처리 오류: {str(e)}")
        emit('error', {'message': str(e)})

# 메인 페이지 데이터 처리
def handle_main_page_data():
    try:
        # 날짜 범위
        today_start, today_end = get_fixed_date_range()
        
        # 1. 일일 고객 수 조회
        daily_customer_count = Customer.query.filter(
            and_(
                Customer.come_in >= today_start,
                Customer.come_in <= today_end
            )
        ).count()
        
        # 2. 일일 도난 의심 고객 수 조회
        daily_suspect_count = Customer.query.filter(
            and_(
                Customer.come_in >= today_start,
                Customer.come_in <= today_end,
                Customer.cal_state == '절도의심'
            )
        ).count()
        
        # 3. 일일 매출액 조회
        daily_sales = 0.0
        
        # 오늘 날짜의 결제 건 조회
        today_payments = Payment.query.filter(
            and_(
                Payment.pay_time >= today_start,
                Payment.pay_time <= today_end
            )
        ).all()
        
        # 결제 건에 해당하는 카트의 총액 합산
        cart_ids = [payment.cart_id for payment in today_payments]
        if cart_ids:
            cart_totals = db.session.query(func.sum(Cart.total_price)).filter(
                Cart.cart_id.in_(cart_ids)
            ).scalar()
            
            if cart_totals is not None:
                daily_sales = float(cart_totals)
        
        # 4. 인기 상품 조회
        # 일별 인기 상품 (DaySales 테이블)
        # 월별 인기 상품 (MonthSales 테이블)


        # 테스트를 위해 고정!!
        # 실제 코드 나중에는 이것을 써야함!! =============================
        # today_str = date.today().strftime('%Y-%m-%d')
        # daily_popular = DaySales.query.filter_by(day=today_str).order_by(
        #     DaySales.count.desc()
        # ).limit(3).all()
        
        # daily_products = [{'product_name': item.product_name, 'count': item.count} for item in daily_popular]     
       
        # current_month = date.today().strftime('%Y-%m')
        # monthly_popular = MonthSales.query.filter_by(month=current_month).order_by(
        #     MonthSales.count.desc()
        # ).limit(3).all()
        
        # monthly_products = [{'product_name': item.product_name, 'count': item.count} for item in monthly_popular]
        
        # # 연별 인기 상품 (YearSales 테이블)
        # current_year = date.today().year
        # yearly_popular = YearSales.query.filter_by(year=current_year).order_by(
        #     YearSales.count.desc()
        # ).limit(3).all()

        #yearly_products = [{'product_name': item.product_name, 'count': item.count} for item in yearly_popular]
        #===============================

        #test data================================
        # 4. 인기 상품 조회
        # fixed_date로부터 형식에 맞는 문자열 생성
        fixed_day_str = datetime(2023, 12, 31).strftime('%Y-%m-%d')  # '2023-12-31'
        fixed_month_str = datetime(2023, 12, 31).strftime('%Y-%m')   # '2023-12'
        fixed_year = 2023

        # 일별 인기 상품 (DaySales 테이블)
        daily_popular = DaySales.query.filter_by(day=fixed_day_str).order_by(
            DaySales.count.desc()
        ).limit(3).all()
        daily_products = [{'product_name': item.product_name, 'count': item.count} for item in daily_popular]  

        # 월별 인기 상품 (MonthSales 테이블)
        monthly_popular = MonthSales.query.filter_by(month=fixed_month_str).order_by(
            MonthSales.count.desc()
        ).limit(3).all()
        monthly_products = [{'product_name': item.product_name, 'count': item.count} for item in monthly_popular]

        # 연별 인기 상품 (YearSales 테이블)
        yearly_popular = YearSales.query.filter_by(year=fixed_year).order_by(
            YearSales.count.desc()
        ).limit(3).all()        
        yearly_products = [{'product_name': item.product_name, 'count': item.count} for item in yearly_popular]

        #test data================================
        
        # 응답 데이터 구성 - 앱에서 요구하는 정확한 키 이름으로 맞춤
        response_data = {
            'daily_customer_count': daily_customer_count,
            'daily_suspect_count': daily_suspect_count,
            'daily_sales': daily_sales,
            'popular_products': {
                'daily': daily_products,
                'monthly': monthly_products,
                'yearly': yearly_products
            }
        }
        
        # 데이터 전송
        emit('mainPageResult', response_data)
        print(f"메인 페이지 데이터 전송 완료: {response_data}")
        
    except Exception as e:
        print(f"메인 페이지 데이터 처리 오류: {str(e)}")
        emit('mainPageResult', {'error': str(e)})

# 알림 페이지 데이터 처리
def handle_alert_page_data(year, stock_lack_count):
    try:
        # 1. 요청된 연도의 도난 의심 고객 데이터 조회
        year_start = f"{year}-01-01 00:00:00"
        year_end = f"{year}-12-31 23:59:59"
        
        suspects = Customer.query.filter(
            and_(
                Customer.come_in >= year_start,
                Customer.come_in <= year_end,
                Customer.cal_state == '절도의심'
            )
        ).all()
        
        suspect_list = []
        for suspect in suspects:
            try:
                # 고객별 카트 조회
                cart = Cart.query.filter_by(customer_id=suspect.customer_id).first()
                
                if cart:
                    # 카트에 담긴 제품 및 수량 조회
                    cart_items_grouped = db.session.query(
                        CartItems.product_name, 
                        func.count(CartItems.product_name).label('count')
                    ).filter(
                        CartItems.cart_id == cart.cart_id
                    ).group_by(
                        CartItems.product_name
                    ).all()
                    
                    # 담긴 제품과 이미지 정보
                    stolen_items = {}
                    stolen_item_images = {}
                    
                    for product_name, count in cart_items_grouped:
                        stolen_items[product_name] = count
                        
                        # 제품 이미지 정보 가져오기
                        product = Product.query.filter_by(product_name=product_name).first()
                        if product and product.product_image:
                            stolen_item_images[product_name] = product.product_image
                
                # 고객 정보 구성
                suspect_data = {
                    'customer_id': suspect.customer_id,
                    'come_in': suspect.come_in.strftime('%Y-%m-%dT%H:%M:%S') if suspect.come_in else None,
                    'come_out': suspect.come_out.strftime('%Y-%m-%dT%H:%M:%S') if suspect.come_out else None,
                    'cal_state': suspect.cal_state,
                    'customer_image': suspect.customer_image,
                    'video_thumbnail': suspect.video_thumbnail,
                    'stolen_items': stolen_items,
                    'stolen_item_images': stolen_item_images
                }
                
                suspect_list.append(suspect_data)
            
            except Exception as e:
                print(f"용의자 데이터 처리 오류 (ID: {suspect.customer_id}): {str(e)}")
        
        # 용의자 데이터 전송
        emit('suspect_data', suspect_list)
        
        # 2. 재고 부족 제품 조회
        stock_alerts = Product.query.filter(
            Product.product_stock < stock_lack_count
        ).all()
        
        stock_alert_list = []
        for item in stock_alerts:
            stock_alert_list.append({
                'id': len(stock_alert_list) + 1,  # 순차적인 ID 부여
                'product_name': item.product_name,
                'product_stock': item.product_stock,
                'min_stock': stock_lack_count,
                'product_image': item.product_image
            })
        
        # 재고 알림 데이터 전송
        emit('stock_data', stock_alert_list)
        
    except Exception as e:
        print(f"알림 페이지 데이터 처리 오류: {str(e)}")
        emit('suspect_data', [])
        emit('stock_data', [])


#=========================    hyechang code ============================



#================================상우=========================================
os.makedirs('cache', exist_ok=True)

@app.route('/api/sales/<int:year>/<int:month>', methods=['GET'])
def get_monthly_sales(year, month):
    """월별 매출 요약 정보만 반환하는 API (날짜별 총액)"""
    
    # 캐시 키 생성
    cache_key = f"sales_summary_{year}_{month}"
    
    # 1. 파일 캐시 확인
    cache_file = f"cache/{cache_key}.json"
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return jsonify(json.load(f))
    except Exception as e:
        print(f"캐시 로드 오류: {str(e)}")
        
    # 2. 현재 월만 조회
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year+1, 1, 1) - timedelta(seconds=1)
    else:
        end_date = datetime(year, month+1, 1) - timedelta(seconds=1)
    
    # 3. 최적화된 쿼리: 날짜별 총액만 GROUP BY로 가져오기
    sales_by_date = db.session.query(
        func.date(Payment.pay_time).label('date'),
        func.sum(Cart.total_price).label('total')
    ).join(
        Cart, Payment.cart_id == Cart.cart_id
    ).filter(
        Payment.pay_time.between(start_date, end_date)
    ).group_by(
        func.date(Payment.pay_time)
    ).all()
    
    result = {}
    
    # 결과 데이터 구성 - 상세 항목 없이 총액만
    for date, total in sales_by_date:
        date_str = date.strftime('%Y-%m-%d')
        result[date_str] = {
            "total": float(total) if total else 0
        }
    
    # 캐시 저장
    try:
        with open(cache_file, 'w') as f:
            json.dump(result, f)
    except Exception as e:
        print(f"캐시 저장 오류: {str(e)}")
        
    response = jsonify(result)
    response.headers['Cache-Control'] = 'public, max-age=86400'  # 24시간 캐싱
    return response

@app.route('/api/sales/day/<string:date_str>', methods=['GET'])
def get_daily_sales_detail(date_str):
    """특정 날짜의 상세 매출 정보를 반환하는 API (고객 ID + 결제 시간별로 묶음)"""

    # 캐시 키 생성
    cache_key = f"salesdetail{date_str}"

    # 1. 파일 캐시 확인
    cache_file = f"cache/{cache_key}.json"
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return jsonify(json.load(f))
    except Exception as e:
        print(f"캐시 로드 오류: {str(e)}")

    try:
        # 날짜 문자열 파싱 (YYYY-MM-DD 형식)
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        next_day = date_obj + timedelta(days=1)
    except ValueError:
        return jsonify({"error": "잘못된 날짜 형식. YYYY-MM-DD 형식이어야 합니다."}), 400

    # 해당 날짜의 총액 계산
    total_sales = db.session.query(
        func.sum(Cart.total_price).label('total')
    ).join(
        Payment, Payment.cart_id == Cart.cart_id
    ).filter(
        Payment.pay_time >= date_obj,
        Payment.pay_time < next_day
    ).scalar()

    # 결과 데이터 구조 초기화
    result = {
        "total": float(total_sales) if total_sales else 0,
        "items": []
    }

    # 고객별 데이터를 임시로 저장할 딕셔너리 - 키는 (고객ID, 결제시간)
    transaction_data = {}

    # 해당 일자의 결제 정보 조회
    payments = Payment.query.filter(
        Payment.pay_time >= date_obj,
        Payment.pay_time < next_day
    ).all()

    for payment in payments:
        cart = db.session.get(Cart, payment.cart_id)
        if not cart:
            continue

        # 고객 정보
        customer = db.session.get(Customer, cart.customer_id)
        customer_id = str(customer.customer_id) if customer else "Unknown"

        # 결제 시간을 문자열로 변환 (시간까지만 정확하게 사용)
        pay_time_str = payment.pay_time.strftime('%Y-%m-%d %H:%M:%S')

        # 트랜잭션 키 생성: 고객 ID + 결제 시간
        transaction_key = f"{customer_id}{pay_time_str}"

        # 해당 트랜잭션이 아직 없으면 초기화
        if transaction_key not in transaction_data:
            transaction_data[transaction_key] = {
                "customer_id": customer_id,
                "pay_time": pay_time_str,
                "amount": 0,
                "products": []
            }

        # 장바구니 상품 - 그룹화하여 중복 줄이기
        cart_items_query = db.session.query(
            CartItems.product_name,
            func.count(CartItems.product_name).label('count')
        ).filter(
            CartItems.cart_id == cart.cart_id
        ).group_by(
            CartItems.product_name
        )

        # 각 상품별로 정보 추가
        for item_info in cart_items_query:
            product_name, count = item_info
            product = db.session.get(Product, product_name)
            if not product:
                continue

            # 상품 정보 및 금액 추가
            item_amount = product.product_price * count
            transaction_data[transaction_key]["amount"] += item_amount
            transaction_data[transaction_key]["products"].append({
                "이름": product_name,
                "가격": product.product_price,
                "수량": count,
                "소계": item_amount
            })

    # 트랜잭션 데이터를 결과 항목으로 변환
    for transaction_key, data in transaction_data.items():
        result["items"].append({
            "amount": data["amount"],
            "description": f"고객 {data['customer_id']} 구매",
            "details": {
                "고객 ID": data["customer_id"],
                "상품 내역": data["products"],
                "시간": data["pay_time"]
            }
        })

    # 캐시 저장
    try:
        with open(cache_file, 'w') as f:
            json.dump(result, f)
    except Exception as e:
        print(f"캐시 저장 오류: {str(e)}")

    response = jsonify(result)
    response.headers['Cache-Control'] = 'public, max-age=86400'  # 24시간 캐싱
    return response


#================================상우=========================================






if __name__ == '__main__':
    with app.app_context():
        # 데이터베이스 테이블 초기화 코드 제거 (이미 존재하는 DB 사용)
        print("서버 시작: 기존 데이터베이스 사용")

        try:
            today = date.today()
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today, datetime.max.time())
            
            # 오늘 입장한 고객 찾기
            todays_customers = Customer.query.filter(
                and_(
                    Customer.come_in >= today_start,
                    Customer.come_in <= today_end
                )
            ).all()
            
            # 고객 ID 목록 출력
            customer_ids = [c.customer_id for c in todays_customers]
            # 고객 데이터 삭제 (Cart, CartItems, Payment는 CASCADE 설정으로 자동 삭제)
            for customer in todays_customers:
                db.session.delete(customer)
            
            db.session.commit()
            print("오늘 데이터베이스 초기화")
        
        except Exception as e:
            db.session.rollback()
            print(f"고객 데이터 삭제 중 오류 발생: {str(e)}")

    # 별도 스레드에서 OpenCV 창 유지
    threading.Thread(target=update_window, daemon=True).start()
    
    print("Flask-SocketIO 서버 실행 중... WebSocket과 HTTP 모두 지원")
    socketio.run(app, host='0.0.0.0', port=5005, debug=True)