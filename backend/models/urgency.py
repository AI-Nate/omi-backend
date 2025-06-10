"""
Pydantic models for urgency assessment
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class UrgencyLevel(str, Enum):
    """Urgency levels for conversation summaries"""
    HIGH = "high"
    MEDIUM = "medium" 
    LOW = "low"


class UrgencyAssessment(BaseModel):
    """Model for urgency assessment of conversation summaries"""
    level: UrgencyLevel = Field(..., description="The urgency level (high, medium, low)")
    reasoning: str = Field(..., description="Explanation for why this urgency level was assigned")
    action_required: bool = Field(..., description="Whether immediate action is required from the user")
    time_sensitivity: str = Field(..., description="Time frame within which action should be taken")
    
    class Config:
        schema_extra = {
            "example": {
                "level": "high",
                "reasoning": "Contains urgent action items with specific deadlines",
                "action_required": True,
                "time_sensitivity": "within 24 hours"
            }
        }


def map_urgency_to_haptic_level(urgency: UrgencyLevel) -> int:
    """
    Map urgency level to haptic intensity level for the device.
    
    Args:
        urgency: UrgencyLevel enum value
        
    Returns:
        int: Haptic level (1=short pulse, 2=medium pulse, 3=long pulse)
    """
    mapping = {
        UrgencyLevel.LOW: 1,     # Short pulse (100ms)
        UrgencyLevel.MEDIUM: 2,  # Medium pulse (300ms) 
        UrgencyLevel.HIGH: 3     # Long pulse (500ms)
    }
    
    return mapping.get(urgency, 1)  # Default to low urgency if unknown 