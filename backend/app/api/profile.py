"""사용자가 직접 입력/편집하는 프로필 데이터: 비교과 활동, 자격증, 어학성적.

성적/전공처럼 One-Stop에서 크롤링해 자동으로 채워지는 데이터(portal_sync.py)와
달리, 여기는 크롤링 대상이 아니라서 사용자가 직접 CRUD로 관리한다.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.users.models import User, UserActivity, UserCertification, UserLanguageScore

router = APIRouter(prefix="/me", tags=["profile"])


# --- 비교과 활동 ---


class ActivityInput(BaseModel):
    title: str
    organization: str | None = None
    category: str | None = None
    role: str | None = None
    award: str | None = None
    description: str | None = None
    url: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


class ActivityResponse(ActivityInput):
    id: int

    model_config = {"from_attributes": True}


def _get_owned_activity(db: Session, user_id: int, activity_id: int) -> UserActivity:
    activity = db.get(UserActivity, activity_id)
    if activity is None or activity.user_id != user_id:
        raise HTTPException(status_code=404, detail="활동을 찾을 수 없습니다")
    return activity


@router.get("/activities", response_model=list[ActivityResponse])
def list_activities(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(UserActivity).where(UserActivity.user_id == current_user.id).order_by(UserActivity.id.desc())
    ).all()


@router.post("/activities", response_model=ActivityResponse, status_code=201)
def create_activity(
    payload: ActivityInput, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    activity = UserActivity(user_id=current_user.id, **payload.model_dump())
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


@router.patch("/activities/{activity_id}", response_model=ActivityResponse)
def update_activity(
    activity_id: int,
    payload: ActivityInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    activity = _get_owned_activity(db, current_user.id, activity_id)
    for field, value in payload.model_dump().items():
        setattr(activity, field, value)
    db.commit()
    db.refresh(activity)
    return activity


@router.delete("/activities/{activity_id}", status_code=204)
def delete_activity(
    activity_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    activity = _get_owned_activity(db, current_user.id, activity_id)
    db.delete(activity)
    db.commit()


# --- 자격증 ---


class CertificationInput(BaseModel):
    name: str
    expires_at: datetime.date | None = None


class CertificationResponse(CertificationInput):
    id: int

    model_config = {"from_attributes": True}


def _get_owned_certification(db: Session, user_id: int, certification_id: int) -> UserCertification:
    certification = db.get(UserCertification, certification_id)
    if certification is None or certification.user_id != user_id:
        raise HTTPException(status_code=404, detail="자격증을 찾을 수 없습니다")
    return certification


@router.get("/certifications", response_model=list[CertificationResponse])
def list_certifications(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(UserCertification)
        .where(UserCertification.user_id == current_user.id)
        .order_by(UserCertification.id.desc())
    ).all()


@router.post("/certifications", response_model=CertificationResponse, status_code=201)
def create_certification(
    payload: CertificationInput, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    certification = UserCertification(user_id=current_user.id, **payload.model_dump())
    db.add(certification)
    db.commit()
    db.refresh(certification)
    return certification


@router.patch("/certifications/{certification_id}", response_model=CertificationResponse)
def update_certification(
    certification_id: int,
    payload: CertificationInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    certification = _get_owned_certification(db, current_user.id, certification_id)
    for field, value in payload.model_dump().items():
        setattr(certification, field, value)
    db.commit()
    db.refresh(certification)
    return certification


@router.delete("/certifications/{certification_id}", status_code=204)
def delete_certification(
    certification_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    certification = _get_owned_certification(db, current_user.id, certification_id)
    db.delete(certification)
    db.commit()


# --- 어학성적 ---


class LanguageScoreInput(BaseModel):
    test_name: str
    score: str
    expires_at: datetime.date | None = None


class LanguageScoreResponse(LanguageScoreInput):
    id: int

    model_config = {"from_attributes": True}


def _get_owned_language_score(db: Session, user_id: int, score_id: int) -> UserLanguageScore:
    score = db.get(UserLanguageScore, score_id)
    if score is None or score.user_id != user_id:
        raise HTTPException(status_code=404, detail="어학성적을 찾을 수 없습니다")
    return score


@router.get("/language-scores", response_model=list[LanguageScoreResponse])
def list_language_scores(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(UserLanguageScore)
        .where(UserLanguageScore.user_id == current_user.id)
        .order_by(UserLanguageScore.id.desc())
    ).all()


@router.post("/language-scores", response_model=LanguageScoreResponse, status_code=201)
def create_language_score(
    payload: LanguageScoreInput, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    score = UserLanguageScore(user_id=current_user.id, **payload.model_dump())
    db.add(score)
    db.commit()
    db.refresh(score)
    return score


@router.patch("/language-scores/{score_id}", response_model=LanguageScoreResponse)
def update_language_score(
    score_id: int,
    payload: LanguageScoreInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    score = _get_owned_language_score(db, current_user.id, score_id)
    for field, value in payload.model_dump().items():
        setattr(score, field, value)
    db.commit()
    db.refresh(score)
    return score


@router.delete("/language-scores/{score_id}", status_code=204)
def delete_language_score(
    score_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    score = _get_owned_language_score(db, current_user.id, score_id)
    db.delete(score)
    db.commit()
