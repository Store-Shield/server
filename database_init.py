from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import time
import pandas as pd
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:csedbadmin@localhost/cctv_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 테이블 모델 정의 (기존 코드와 동일)
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

class Cart(db.Model):
    __tablename__ = 'cart'
    
    cart_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.customer_id', ondelete='CASCADE'), nullable=False)
    total_price = db.Column(db.Float)
    
    cart_items = db.relationship('CartItems', backref='cart', lazy=True,
                                cascade="all, delete-orphan")
    payments = db.relationship('Payment', backref='cart', lazy=True,
                              cascade="all, delete-orphan")

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


# CSV 파일에서 데이터 불러와 DB에 저장하는 함수
def load_data_from_csv():
    csv_dir = "Dummy"  # CSV 파일이 있는 디렉토리
    
    # 각 CSV 파일 경로
    customer_csv = os.path.join(csv_dir, "Customer.csv")
    cart_csv = os.path.join(csv_dir, "Cart.csv")
    cart_items_csv = os.path.join(csv_dir, "CartItems.csv")
    payment_csv = os.path.join(csv_dir, "Payment.csv")
    product_csv = os.path.join(csv_dir, "Product.csv")
    day_sales_csv = os.path.join(csv_dir, "DaySales.csv")
    month_sales_csv = os.path.join(csv_dir, "MonthSales.csv")
    year_sales_csv = os.path.join(csv_dir, "YearSales.csv")
    
    # 1. 제품 데이터 로드 (다른 테이블의 외래키 참조를 위해 먼저 로드)
    try:
        products_df = pd.read_csv(product_csv)
        for _, row in products_df.iterrows():
            product = Product(
                product_name=row['product_name'],
                product_price=row['product_price'],
                product_image=row['product_image'],
                product_stock=row['product_stock']
            )
            db.session.add(product)
        db.session.commit()
        print(f"제품 데이터 {len(products_df)}개 로드 완료")
    except Exception as e:
        print(f"제품 데이터 로드 오류: {e}")
        db.session.rollback()
    
    # 2. 고객 데이터 로드
    try:
        customers_df = pd.read_csv(customer_csv)
        print(f"고객 CSV 파일 내용:")
        print(customers_df)
        print(f"총 {len(customers_df)}개의 행이 있습니다.")
        for _, row in customers_df.iterrows():
            # 날짜/시간 문자열을 datetime 객체로 변환
            come_in = datetime.strptime(row['come_in'], '%Y-%m-%d %H:%M:%S') if not pd.isna(row['come_in']) else None
            come_out = datetime.strptime(row['come_out'], '%Y-%m-%d %H:%M:%S') if not pd.isna(row['come_out']) else None
            
            customer = Customer(
                customer_id=row['customer_id'],
                come_in=come_in,
                come_out=come_out,
                cal_state=row['cal_state'],
                customer_image=row['customer_image']
            )
            db.session.add(customer)
        db.session.commit()
        print(f"고객 데이터 {len(customers_df)}개 로드 완료")
    except Exception as e:
        print(f"고객 데이터 로드 오류: {e}")
        db.session.rollback()
    
    # 3. 장바구니 데이터 로드
    try:
        carts_df = pd.read_csv(cart_csv)
        for _, row in carts_df.iterrows():
            cart = Cart(
                cart_id=row['cart_id'],
                customer_id=row['customer_id'],
                total_price=row['total_price']
            )
            db.session.add(cart)
        db.session.commit()
        print(f"장바구니 데이터 {len(carts_df)}개 로드 완료")
    except Exception as e:
        print(f"장바구니 데이터 로드 오류: {e}")
        db.session.rollback()
    
    # 4. 장바구니 아이템 데이터 로드
    try:
        cart_items_df = pd.read_csv(cart_items_csv)
        for _, row in cart_items_df.iterrows():
            cart_item = CartItems(
                auto_id=row['auto_id'],
                cart_id=row['cart_id'],
                product_name=row['product_name']
            )
            db.session.add(cart_item)
        db.session.commit()
        print(f"장바구니 아이템 데이터 {len(cart_items_df)}개 로드 완료")
    except Exception as e:
        print(f"장바구니 아이템 데이터 로드 오류: {e}")
        db.session.rollback()
    
    # 5. 결제 데이터 로드
    try:
        payments_df = pd.read_csv(payment_csv)
        for _, row in payments_df.iterrows():
            # 날짜/시간 문자열을 datetime 객체로 변환
            pay_time = datetime.strptime(row['pay_time'], '%Y-%m-%d %H:%M:%S') if not pd.isna(row['pay_time']) else None
            
            payment = Payment(
                pay_id=row['pay_id'],
                pay_time=pay_time,
                cart_id=row['cart_id']
            )
            db.session.add(payment)
        db.session.commit()
        print(f"결제 데이터 {len(payments_df)}개 로드 완료")
    except Exception as e:
        print(f"결제 데이터 로드 오류: {e}")
        db.session.rollback()
    
    # 6. 일별 판매 데이터 로드
    try:
        day_sales_df = pd.read_csv(day_sales_csv)
        for _, row in day_sales_df.iterrows():
            day_sale = DaySales(
                day=row['day'],
                product_name=row['product_name'],
                count=row['count']
            )
            db.session.add(day_sale)
        db.session.commit()
        print(f"일별 판매 데이터 {len(day_sales_df)}개 로드 완료")
    except Exception as e:
        print(f"일별 판매 데이터 로드 오류: {e}")
        db.session.rollback()
    
    # 7. 월별 판매 데이터 로드
    try:
        month_sales_df = pd.read_csv(month_sales_csv)
        for _, row in month_sales_df.iterrows():
            month_sale = MonthSales(
                month=row['month'],
                product_name=row['product_name'],
                count=row['count']
            )
            db.session.add(month_sale)
        db.session.commit()
        print(f"월별 판매 데이터 {len(month_sales_df)}개 로드 완료")
    except Exception as e:
        print(f"월별 판매 데이터 로드 오류: {e}")
        db.session.rollback()
    
    # 8. 연도별 판매 데이터 로드
    try:
        year_sales_df = pd.read_csv(year_sales_csv)
        for _, row in year_sales_df.iterrows():
            year_sale = YearSales(
                year=row['year'],
                product_name=row['product_name'],
                count=row['count']
            )
            db.session.add(year_sale)
        db.session.commit()
        print(f"연도별 판매 데이터 {len(year_sales_df)}개 로드 완료")
    except Exception as e:
        print(f"연도별 판매 데이터 로드 오류: {e}")
        db.session.rollback()


# 데이터베이스 초기화 및 데이터 로드 함수
def init_db():
    # 모든 테이블 삭제 후 재생성
    db.drop_all()
    db.create_all()
    print("데이터베이스 테이블 생성 완료")
    
    # CSV 파일에서 데이터 로드
    load_data_from_csv()
    print("CSV 파일에서 데이터 로드 완료")


if __name__ == '__main__':
    with app.app_context():
        init_db()
        print("데이터베이스 초기화가 완료되었습니다.")