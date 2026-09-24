from typing import Dict, Any
from config.db_conf import get_db
from utils.common import rm_characters
from sqlalchemy.ext.asyncio import AsyncSession
from crud import Character, Project, CharacterStage
from schemas.Character import CharacterDetail, CharacterCreate
from fastapi import APIRouter, Depends, Query, Path, HTTPException, Body



router = APIRouter(prefix="/autostory/character", tags=["character"])


@router.get("/characters")
async def get_characters(
        project_id: int = Query(...),
        page: int = Query(..., gt=0),
        pagesize: int = Query(10, gt=0),
        db: AsyncSession = Depends(get_db)
):
    offset = (page - 1) * pagesize
    characters, total = await Character.get_characters_by_paginated(db, project_id, offset, pagesize)
    has_more = (offset + len(characters)) < total
    characters = [CharacterDetail.model_validate(character) for character in characters]
    return {
        "data": {
            "List": characters,
            "Total": total,
            "More": has_more
        }
    }


@router.post("/add_character")
async def add_character(
        project_id: int,
        character: CharacterCreate,
        db: AsyncSession = Depends(get_db)
):
    character = await Character.add_character_by_model(db,character)
    await Project.add_project_character(db,project_id,character.id)
    return {
        "data": {
            "Character": character,
            "Resp": "创建成功"
        }
    }


@router.get("/{character_id}")
async def get_character(
        character_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    character = await Character.get_character_by_id(db, character_id)
    return {
        "data": {
            "Character": CharacterDetail.model_validate(character)
        }
    }


@router.put("/{character_id}")
async def update_character(
        character_id: int = Path(...),
        update_data: Dict[str, Any] = Body(...),
        db: AsyncSession = Depends(get_db)
):
    if not update_data:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    updated_character = await Character.update_character(db, character_id, update_data)

    if not updated_character:
        raise HTTPException(status_code=404, detail="角色不存在")

    return updated_character

@router.delete("/{character_id}")
async def delete_character(
        character_id: int = Path(...),
        db: AsyncSession = Depends(get_db)
):
    characterstageids = await Character.get_stage_ids_by_character_id(db,character_id)
    await CharacterStage.delete_stages_by_character(db,character_id)
    await Character.remove_character_stage_by_character(db,character_id)
    await Character.delete_character(db, character_id)
    await db.commit()

    await rm_characters(characterstageids)
    return {
        "data": {
            "Resp": "删除成功"
        }
    }
