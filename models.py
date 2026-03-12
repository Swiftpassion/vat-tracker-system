import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ดึง URL ของ Supabase ที่เราซ่อนไว้ใน Environment Variables ของระบบ
SUPABASE_DB_URL = os.getenv("DATABASE_URL") 

# สร้างตัวเชื่อมต่อ (Engine) ไปยัง Supabase
engine = create_engine(SUPABASE_DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)