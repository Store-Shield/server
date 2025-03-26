from flask import Flask, request, jsonify,render_template
import base64
import cv2
import numpy as np
import os
from flask_socketio import SocketIO, emit
import threading
from flask_sqlalchemy import SQLAlchemy  # 추가
from datetime import datetime  # 추가
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
# 전역 변수로 이미지 저장
current_image = None
base64_image=None

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:csedbadmin@localhost/cctv_db'#db 연결
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 키오스크 위치 정보 저장
kiosk_request_pending = False
kiosk_waiting_client = None


# 제품 매핑 정의
PRODUCT_MAPPING = {
    'cup': 'product1',
    'book': 'product2',
    'phone': 'product3'
}


# 데이터베이스 모델 정의
class CustomerCart(db.Model):
    __tablename__ = 'customer_carts'
    
    person_id = db.Column(db.Integer,  primary_key=True)
    product1 = db.Column(db.Integer, default=0)
    product2 = db.Column(db.Integer, default=0)
    product3 = db.Column(db.Integer, default=0)
    state = db.Column(db.String(20), default='결제대기')  # 결제대기, 결제중, 결제완료, 절도
    
    def to_dict(self):
        return {
           
            'person_id': self.person_id,
            'product1': self.product1,
            'product2': self.product2,
            'product3': self.product3,
            'state': self.state,
            
        }




def update_window():
    global current_image
    while True:
        if current_image is not None:
            cv2.imshow("Received Image", current_image)
            cv2.waitKey(1)
            
            
@app.route('/')
@app.route('/show')
def show():
    customers = CustomerCart.query.all()
    # 객체를 사전 목록으로 변환
    customers_dict = [customer.to_dict() for customer in customers]
    return render_template('real_time_cctv_analysis.html', customers=customers_dict)


@app.route('/kiosk')
def kiosk():
    return render_template('kiosk.html')



# 웹소켓 연결 이벤트
@socketio.on('connect')
def handle_connect():
    print('클라이언트 연결됨')
    
    
@socketio.on('request_update')
def handle_update_request():
    global base64_image
    try:
        # 모든 고객 정보 가져오기
        customers = CustomerCart.query.all()
        customer_data = [customer.to_dict() for customer in customers]
        
        # 현재 이미지와 고객 정보를 함께 전송
        if base64_image:
            emit('update', {
                'image': base64_image,
                'customers': customer_data
            })
    except Exception as e:
        print(f"업데이트 요청 처리 오류: {str(e)}")    
        

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
                # 해당 고객의 DB 정보 조회
                customer = CustomerCart.query.filter_by(person_id=person_id).first()
                
                if customer:
                    if (customer.product1 == 0 and customer.product2 == 0 and customer.product3 == 0):
                         # 키오스크에 고객 정보 전송 #1이면 정상 0이면 장바구니에 담긴게 없음 -1이면 고객이 찾을 수 없음
                        emit('customer_info', {
                            'success': 0,
                            'customer': customer.to_dict()
                        }, to=kiosk_waiting_client)
                    else:
                        # 고객 상태를 결제중으로 변경
                        if customer.state == '결제대기':
                            customer.state = '결제중'
                            db.session.commit()

                        # 키오스크에 고객 정보 전송 #1이면 정상 0이면 장바구니에 담긴게 없음 -1이면 고객이 찾을 수 없음
                        emit('customer_info', {
                            'success': 1,
                            'customer': customer.to_dict()
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
            customer = CustomerCart.query.filter_by(person_id=customer_id).first()
            
            if customer:
                # 고객 상태를 결제완료로 변경
                customer.state = '결제완료'
                db.session.commit()
                
                # 결제 완료 응답
                emit('payment_completed', {'success': True})
                
                # 실시간 모니터링 화면 업데이트 요청
                customers = CustomerCart.query.all()
                customer_data = [c.to_dict() for c in customers]
                emit('update', {
                    'image': base64_image,
                    'customers': customer_data
                }, broadcast=True)
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
            
            if not base64_image:
                return

            #이후에는 코드 지워도 됨=========================================
            # Base64 디코딩 및 이미지 변환
            image_data = base64.b64decode(base64_image)
            nparr = np.frombuffer(image_data, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if image is None:
                print("이미지 디코딩 실패")
                return

            # 이미지 처리
            resized_image = cv2.resize(image, (800,700))
            current_image = resized_image
            #print("웹소켓을 통해 이미지 수신 및 업데이트")
            #=======================================================

            # 클라이언트에 응답 (선택사항)
            emit('response', {'status': 'success'})
        elif data.get('type') == 'personAppearance':
            timestamp=data.get('timestamp')
            personIds=data.get('personIds')   
            print(f"{timestamp} 시간에 {personIds} 등장")
            for person_id in personIds:
                # 이미 존재하는지 확인
                customer = CustomerCart.query.filter_by(person_id=person_id).first()
                if not customer:
                    # 새 고객 생성
                    new_customer = CustomerCart(
                        person_id=person_id, 
                        product1=0, 
                        product2=0, 
                        product3=0, 
                        state='결제대기'
                    )
                    db.session.add(new_customer)
                    db.session.commit()
                    print(f"고객 ID {person_id} DB에 추가됨")
                    
                    
        elif data.get('type') == 'personDisappearance':
            timestamp=data.get('timestamp')
            personIds=data.get('personIds')
            print(f"{timestamp} 시간에 {personIds} 없어짐")
            
            
             # 고객 상태 업데이트
            for person_id in personIds:
                customer = CustomerCart.query.filter_by(person_id=person_id).first()
                if customer:
                    # 상품을 가지고 있고 결제완료 상태가 아니면 절도로 표시
                    if (customer.state == '결제대기' and 
    (customer.product1 > 0 or customer.product2 > 0 or customer.product3 > 0)):
                        customer.state = '절도의심'
                        db.session.commit()
                        print(f"고객 ID {person_id} 절도 의심")
                    elif (customer.state == '결제중' and 
    (customer.product1 > 0 or customer.product2 > 0 or customer.product3 > 0)):
                        customer.state = '절도의심'
                        db.session.commit()
                        print(f"고객 ID {person_id} 절도 의심")    
                    elif customer.state == '결제완료':
                        # 결제 완료된 고객은 DB에서 삭제
                        #db.session.delete(customer)
                        db.session.commit()
                        print(f"고객 ID {person_id} 결제 완료")
                    elif (customer.state == '결제대기' and customer.product1== 0 and customer.product2 ==0 and customer.product3 == 0):
                        customer.state = '일반퇴장'
                        db.session.commit()
                        print(f"고객 ID {person_id} 일반퇴장")
                        
        elif data.get('type') == 'action':
            person_id = data.get('personId')
            product_name = data.get('object')  # cup, book, phone 제품 종류 수정부분!!!!!!!!!1
            act = data.get('act')  # 0: 내려놓음, 1: 집음
            
            # DB에서 고객 정보 조회
            customer = CustomerCart.query.filter_by(person_id=person_id).first()
            
            if not customer:
                print("customer 매칭 오류")
                return
               
            # 제품 매핑에 따라 해당 제품 필드 업데이트
            if product_name in PRODUCT_MAPPING:
                product_field = PRODUCT_MAPPING[product_name]
                
                if act == 1:  # 집음
                    current_value = getattr(customer, product_field, 0)
                    setattr(customer, product_field, current_value + 1)
                    action_text = "집었습니다"
                elif act == 0:  # 내려놓음
                    current_value = getattr(customer, product_field, 0)
                    if current_value > 0:
                        setattr(customer, product_field, current_value - 1)
                    action_text = "내려놓았습니다"
                
                db.session.commit()
                print(f"{person_id}가 {product_name}을 {action_text}")
           
            

    except Exception as e:
        print(f"웹소켓 처리 오류: {str(e)}")
        
        
        
        
if __name__ == '__main__':
    
    with app.app_context():
        db.drop_all()  # 모든 테이블을 삭제
        db.create_all()  # 데이터베이스 테이블 생성
        print("db 연결 완료")

    # 별도 스레드에서 OpenCV 창 유지
    threading.Thread(target=update_window, daemon=True).start()

    # cctv->html로 전송
    #threading.Thread(target=update_html, daemon=True).start()

    print("Flask-SocketIO 서버 실행 중... WebSocket과 HTTP 모두 지원")
    socketio.run(app, host='0.0.0.0', port=5005, debug=True)