from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, field_validator
from typing import List, Literal, Optional
from datetime import date
import os
import re

from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Date,
    Enum,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

# ── Database configuration ─────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://USER:PASSWORD@HOST/DATABASE")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── ORM models ─────────────────────────────────────────────────────────────────

class EmployeeModel(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    department = Column(String, nullable=False)

    attendance_records = relationship(
        "AttendanceModel", back_populates="employee", cascade="all, delete-orphan"
    )


class AttendanceModel(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "date", name="uq_employee_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"))
    date = Column(Date, nullable=False)
    status = Column(String, nullable=False)

    employee = relationship("EmployeeModel", back_populates="attendance_records")


Base.metadata.create_all(bind=engine)


app = FastAPI(title="HRMS Lite API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Schemas ──────────────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    employee_id: str
    full_name: str
    email: str
    department: str

    @field_validator("employee_id")
    @classmethod
    def validate_employee_id(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Employee ID is required")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Full name is required")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        v = v.strip().lower()
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("department")
    @classmethod
    def validate_department(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Department is required")
        return v


class Employee(EmployeeCreate):
    pass


class AttendanceCreate(BaseModel):
    employee_id: str
    date: str
    status: Literal["Present", "Absent"]

    @field_validator("employee_id")
    @classmethod
    def validate_employee_id(cls, v):
        if not v.strip():
            raise ValueError("Employee ID is required")
        return v.strip()

    @field_validator("date")
    @classmethod
    def validate_date(cls, v):
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("Invalid date format. Use YYYY-MM-DD")
        return v


class AttendanceRecord(AttendanceCreate):
    pass


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "HRMS Lite API is running", "version": "1.0.0"}


# Employees

@app.get("/employees", response_model=List[Employee])
def list_employees(db: Session = Depends(get_db)):
    employees = db.query(EmployeeModel).all()
    return [
        Employee(
            employee_id=e.employee_id,
            full_name=e.full_name,
            email=e.email,
            department=e.department,
        )
        for e in employees
    ]


@app.post("/employees", response_model=Employee, status_code=201)
def create_employee(data: EmployeeCreate, db: Session = Depends(get_db)):
    # Check duplicate employee_id
    existing_by_id = (
        db.query(EmployeeModel)
        .filter(EmployeeModel.employee_id == data.employee_id)
        .first()
    )
    if existing_by_id:
        raise HTTPException(
            status_code=409,
            detail=f"Employee with ID '{data.employee_id}' already exists",
        )

    # Check duplicate email
    existing_by_email = (
        db.query(EmployeeModel).filter(EmployeeModel.email == data.email).first()
    )
    if existing_by_email:
        raise HTTPException(
            status_code=409,
            detail=f"Email '{data.email}' is already registered",
        )

    employee = EmployeeModel(
        employee_id=data.employee_id,
        full_name=data.full_name,
        email=data.email,
        department=data.department,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)

    return Employee(
        employee_id=employee.employee_id,
        full_name=employee.full_name,
        email=employee.email,
        department=employee.department,
    )


@app.get("/employees/{employee_id}", response_model=Employee)
def get_employee(employee_id: str, db: Session = Depends(get_db)):
    employee = (
        db.query(EmployeeModel)
        .filter(EmployeeModel.employee_id == employee_id)
        .first()
    )
    if not employee:
        raise HTTPException(
            status_code=404, detail=f"Employee '{employee_id}' not found"
        )

    return Employee(
        employee_id=employee.employee_id,
        full_name=employee.full_name,
        email=employee.email,
        department=employee.department,
    )


@app.delete("/employees/{employee_id}")
def delete_employee(employee_id: str, db: Session = Depends(get_db)):
    employee = (
        db.query(EmployeeModel)
        .filter(EmployeeModel.employee_id == employee_id)
        .first()
    )
    if not employee:
        raise HTTPException(
            status_code=404, detail=f"Employee '{employee_id}' not found"
        )

    db.delete(employee)
    db.commit()

    return {"message": f"Employee '{employee_id}' deleted successfully"}


# Attendance

@app.get("/attendance", response_model=List[AttendanceRecord])
def list_attendance(
    employee_id: Optional[str] = None,
    date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(AttendanceModel).join(EmployeeModel)

    if employee_id:
        query = query.filter(EmployeeModel.employee_id == employee_id)

    if date:
        try:
            date_obj = date_from_str = date and date.split("T")[0]
            date_parsed = date_obj
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Use YYYY-MM-DD",
            )
    records = query.all()

    result: List[AttendanceRecord] = []
    for rec in records:
        result.append(
            AttendanceRecord(
                employee_id=rec.employee.employee_id,
                date=rec.date.isoformat(),
                status=rec.status,
            )
        )
    return result


@app.post("/attendance", response_model=AttendanceRecord, status_code=201)
def mark_attendance(data: AttendanceCreate, db: Session = Depends(get_db)):
    employee = (
        db.query(EmployeeModel)
        .filter(EmployeeModel.employee_id == data.employee_id)
        .first()
    )
    if not employee:
        raise HTTPException(
            status_code=404, detail=f"Employee '{data.employee_id}' not found"
        )

    attendance_date = date.fromisoformat(data.date)

    record = (
        db.query(AttendanceModel)
        .filter(
            AttendanceModel.employee_id == employee.id,
            AttendanceModel.date == attendance_date,
        )
        .first()
    )

    if record:
        record.status = data.status
    else:
        record = AttendanceModel(
            employee_id=employee.id,
            date=attendance_date,
            status=data.status,
        )
        db.add(record)

    db.commit()
    db.refresh(record)

    return AttendanceRecord(
        employee_id=employee.employee_id,
        date=record.date.isoformat(),
        status=record.status,
    )