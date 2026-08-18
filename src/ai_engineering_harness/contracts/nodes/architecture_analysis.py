from typing import Literal

from pydantic import BaseModel, Field


class ArchitectureAnalysisInput(BaseModel):
    requirement_id: str = Field(description="ID do requisito em análise")
    current_architecture: dict[str, object] = Field(
        description="Representação do estado arquitetural atual"
    )
    affected_modules: list[str] = Field(description="Módulos potencialmente impactados")
    non_functional_requirements: list[str] = Field(
        default_factory=list, description="Requisitos não funcionais a preservar"
    )


class ArchitectureAnalysisOutput(BaseModel):
    impact_level: Literal["low", "medium", "high", "critical"] = Field(
        description="Nível de impacto na arquitetura existente"
    )
    required_changes: list[str] = Field(description="Lista de alterações estruturais necessárias")
    adr_required: bool = Field(description="Indica se é necessário criar/atualizar um ADR")
    approval_required: bool = Field(description="Indica se requer aprovação humana antes da implementação")
