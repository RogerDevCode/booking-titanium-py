from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.domain.enums import BookingStatus

class TelegramUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    username: Optional[str] = None
    first_name: str
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    rut: Optional[str] = None

class Specialty(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: Optional[str] = None

class Provider(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    specialty_id: str
    bio: Optional[str] = None
    is_active: bool = True
    waitlist_batch_size: int = 3
    waitlist_delay_minutes: int = 15
    slot_duration_minutes: int = 30
    buffer_time_minutes: int = 0
    notice_period_hours: int = 4
    gcal_calendar_id: Optional[str] = None
    gcal_access_token: Optional[str] = None
    gcal_refresh_token: Optional[str] = None
    gcal_client_id: Optional[str] = None
    gcal_client_secret: Optional[str] = None

class AppointmentSlot(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    doctor_id: str
    start_time: datetime
    end_time: datetime
    is_available: bool = True

class Booking(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    slot_id: str
    status: BookingStatus
    created_at: datetime
    updated_at: datetime

class BookingView(BaseModel):
    id: int
    status: BookingStatus
    start_time: datetime
    provider_name: str
    specialty_name: str

class WaitlistEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: int
    provider_id: str
    status: str
    created_at: datetime
    updated_at: datetime

class WaitlistNotification(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    waitlist_id: str
    slot_id: str
    notified_at: datetime

class ProviderSchedule(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider_id: str
    day_of_week: int
    start_time: str
    end_time: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class ProviderException(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider_id: str
    start_datetime: datetime
    end_datetime: datetime
    reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class ReminderPreferences(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    telegram_enabled: bool = True
    email_enabled: bool = False
    window_24h: bool = True
    window_2h: bool = True
    updated_at: Optional[datetime] = None

class WaitlistEntryView(BaseModel):
    id: int
    user_id: int
    created_at: datetime
    first_name: str
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    rut: Optional[str] = None

