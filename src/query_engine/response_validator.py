from __future__ import annotations

from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, ConfigDict, ValidationError, create_model


def _resolve_primitive_type(
    type_name: str,
) -> Any:
    """Resolve one primitive type from the lightweight schema."""

    type_name = type_name.strip().lower()

    mapping: Dict[str, Any] = {
        "string": str,
        "number": float,
        "integer": int,
        "boolean": bool,
        "null": type(None),
        "object": Dict[str, Any],
        "array": List[Any],
    }

    return mapping.get(
        type_name,
        Any,
    )


def resolve_schema_type(
    schema_type: str,
) -> Any:
    """
    Convert the custom response schema syntax into a Python type.

    Examples:
        string
        number
        string|null
        string|array|null
        array
    """

    if not isinstance(
        schema_type,
        str,
    ):
        return Any

    parts = [
        part.strip()
        for part in schema_type.split("|")
        if part.strip()
    ]

    if not parts:
        return Any

    resolved_types = [
        _resolve_primitive_type(part)
        for part in parts
    ]

    if len(resolved_types) == 1:
        return resolved_types[0]

    return Union[
        tuple(resolved_types)
    ]


def build_response_model(
    response_schema: Dict[str, str],
    model_name: str,
) -> Type[BaseModel]:
    """
    Dynamically build a Pydantic model from response_schema.

    Unknown fields are rejected.
    """

    fields: Dict[str, Any] = {}

    for field_name, field_type in response_schema.items():

        resolved_type = resolve_schema_type(
            field_type
        )

        nullable = (
            isinstance(field_type, str)
            and "null" in field_type
        )

        default: Any = None if nullable else ...

        fields[field_name] = (
            resolved_type,
            default,
        )

    return create_model(
        model_name,
        __config__=ConfigDict(
            extra="forbid"
        ),
        **fields,
    )


def validate_answer(
    answer: Any,
    response_type: str,
    response_schema: Dict[str, str],
    query_id: str,
) -> Any:
    """
    Validate an LLM answer against the query's dynamic response schema.

    Returns:
        Validated Python data.

    Raises:
        ValueError:
            When the answer does not match the expected structure.
    """

    if not isinstance(
        response_schema,
        dict,
    ):
        raise ValueError(
            f"{query_id}: response_schema must be an object."
        )

    if response_type == "object":

        if not isinstance(
            answer,
            dict,
        ):
            raise ValueError(
                f"{query_id}: expected JSON object, "
                f"got {type(answer).__name__}."
            )

        model = build_response_model(
            response_schema=response_schema,
            model_name=f"{query_id}Response",
        )

        try:
            validated = model.model_validate(
                answer
            )

        except ValidationError as exc:
            raise ValueError(
                f"{query_id}: Pydantic validation failed: "
                f"{exc}"
            ) from exc

        return validated.model_dump()

    if response_type == "array":

        if not isinstance(
            answer,
            list,
        ):
            raise ValueError(
                f"{query_id}: expected JSON array, "
                f"got {type(answer).__name__}."
            )

        model = build_response_model(
            response_schema=response_schema,
            model_name=f"{query_id}Item",
        )

        validated_items: List[Any] = []

        for index, item in enumerate(answer):

            if not isinstance(
                item,
                dict,
            ):
                raise ValueError(
                    f"{query_id}: array item {index} "
                    f"must be an object."
                )

            try:
                validated = model.model_validate(
                    item
                )

            except ValidationError as exc:
                raise ValueError(
                    f"{query_id}: Pydantic validation failed "
                    f"for array item {index}: {exc}"
                ) from exc

            validated_items.append(
                validated.model_dump()
            )

        return validated_items

    raise ValueError(
        f"{query_id}: unsupported response_type "
        f"'{response_type}'."
    )