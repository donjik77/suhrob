from aiogram.types import MessageEntity


def dump_message_entities(entities: list[MessageEntity] | None) -> list[dict] | None:
    if not entities:
        return None
    return [entity.model_dump(mode="json") for entity in entities]


def load_message_entities(entities_json: list[dict] | None) -> list[MessageEntity] | None:
    if not entities_json:
        return None
    return [
        entity if isinstance(entity, MessageEntity) else MessageEntity.model_validate(entity)
        for entity in entities_json
    ]
