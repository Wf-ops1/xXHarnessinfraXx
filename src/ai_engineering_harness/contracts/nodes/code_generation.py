from pydantic import BaseModel, Field


class CodeGenerationInput(BaseModel):
    requirement_id: str = Field(description="ID da funcionalidade a implementar")
    architecture_spec: dict[str, object] = Field(
        description="Especificação da arquitetura e contratos aprovados"
    )
    affected_files: list[str] = Field(description="Lista de arquivos alvos para alteração")
    retry_context: dict[str, object] | None = Field(
        default=None, description="Contexto de erro da tentativa anterior em caso de retry"
    )


class CodeGenerationOutput(BaseModel):
    modified_files: list[str] = Field(description="Arquivos alterados ou criados")
    summary: str = Field(description="Resumo claro das modificações efetuadas")
    success: bool = Field(description="Status da geração de código pelo agente")
