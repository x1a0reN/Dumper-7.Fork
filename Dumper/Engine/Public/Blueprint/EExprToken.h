#pragma once

#include <cstdint>

// UE Blueprint VM opcodes (EExprToken)
// Reference: Runtime/CoreUObject/Public/UObject/Script.h
enum class EExprToken : uint8_t
{
	EX_LocalVariable        = 0x00,
	EX_InstanceVariable     = 0x01,
	EX_DefaultVariable      = 0x02,
	EX_Return               = 0x04,
	EX_Jump                 = 0x06,
	EX_JumpIfNot            = 0x07,
	EX_Assert               = 0x09,
	EX_Nothing              = 0x0B,
	EX_Let                  = 0x0F,
	EX_ClassContext          = 0x12,
	EX_MetaCast             = 0x13,
	EX_LetBool              = 0x14,
	EX_EndParmValue         = 0x15,
	EX_EndFunctionParms     = 0x16,
	EX_Self                 = 0x17,
	EX_Skip                 = 0x18,
	EX_Context              = 0x19,
	EX_Context_FailSilent   = 0x1A,
	EX_VirtualFunction      = 0x1B,
	EX_FinalFunction        = 0x1C,
	EX_IntConst             = 0x1D,
	EX_FloatConst           = 0x1E,
	EX_StringConst          = 0x1F,
	EX_ObjectConst          = 0x20,
	EX_NameConst            = 0x21,
	EX_RotationConst        = 0x22,
	EX_VectorConst          = 0x23,
	EX_ByteConst            = 0x24,
	EX_IntZero              = 0x25,
	EX_IntOne               = 0x26,
	EX_True                 = 0x27,
	EX_False                = 0x28,
	EX_TextConst            = 0x2C,
	EX_NoObject             = 0x2A,
	EX_TransformConst       = 0x2B,
	EX_IntConstByte         = 0x2D,
	EX_NoInterface          = 0x2E,
	EX_DynamicCast          = 0x2F,
	EX_StructConst          = 0x30,
	EX_EndStructConst       = 0x31,
	EX_SetArray             = 0x32,
	EX_EndArray             = 0x33,
	EX_PropertyConst        = 0x34,
	EX_UnicodeStringConst   = 0x35,
	EX_Int64Const           = 0x36,
	EX_UInt64Const          = 0x37,
	EX_DoubleConst          = 0x38,
	EX_SetSet               = 0x39,
	EX_EndSet               = 0x3A,
	EX_SetMap               = 0x3B,
	EX_EndMap               = 0x3C,
	EX_SetConst             = 0x3D,
	EX_EndSetConst          = 0x3E,
	EX_MapConst             = 0x3F,
	EX_EndMapConst          = 0x40,
	EX_StructMemberContext  = 0x42,
	EX_LetMulticastDelegate = 0x43,
	EX_LetDelegate          = 0x44,
	EX_LocalVirtualFunction = 0x45,
	EX_LocalFinalFunction   = 0x46,
	EX_LocalOutVariable     = 0x48,
	EX_DeprecatedOp4A       = 0x4A,
	EX_InstanceDelegate     = 0x4B,
	EX_PushExecutionFlow    = 0x4C,
	EX_PopExecutionFlow     = 0x4D,
	EX_ComputedJump         = 0x4E,
	EX_PopExecutionFlowIfNot = 0x4F,
	EX_Breakpoint           = 0x50,
	EX_InterfaceContext     = 0x51,
	EX_ObjToInterfaceCast   = 0x52,
	EX_EndOfScript          = 0x53,
	EX_CrossInterfaceCast   = 0x54,
	EX_InterfaceToObjCast   = 0x55,
	EX_WireTracepoint       = 0x5A,
	EX_SkipOffsetConst      = 0x5B,
	EX_AddMulticastDelegate = 0x5C,
	EX_ClearMulticastDelegate = 0x5D,
	EX_Tracepoint           = 0x5E,
	EX_LetObj               = 0x5F,
	EX_LetWeakObjPtr        = 0x60,
	EX_BindDelegate         = 0x61,
	EX_RemoveMulticastDelegate = 0x62,
	EX_CallMulticastDelegate = 0x63,
	EX_LetValueOnPersistentFrame = 0x64,
	EX_ArrayConst           = 0x65,
	EX_EndArrayConst        = 0x66,
	EX_SoftObjectConst      = 0x67,
	EX_CallMath             = 0x68,
	EX_SwitchValue          = 0x69,
	EX_InstrumentationEvent = 0x6A,
	EX_ArrayGetByRef        = 0x6B,
	EX_ClassSparseDataVariable = 0x6C,
	EX_FieldPathConst       = 0x6D,
	EX_Max                  = 0xFF,
};

// Get opcode name string
inline const char* GetExprTokenName(EExprToken Token)
{
	switch (Token)
	{
	case EExprToken::EX_LocalVariable:        return "LocalVariable";
	case EExprToken::EX_InstanceVariable:     return "InstanceVariable";
	case EExprToken::EX_DefaultVariable:      return "DefaultVariable";
	case EExprToken::EX_Return:               return "Return";
	case EExprToken::EX_Jump:                 return "Jump";
	case EExprToken::EX_JumpIfNot:            return "JumpIfNot";
	case EExprToken::EX_Assert:               return "Assert";
	case EExprToken::EX_Nothing:              return "Nothing";
	case EExprToken::EX_Let:                  return "Let";
	case EExprToken::EX_ClassContext:         return "ClassContext";
	case EExprToken::EX_MetaCast:             return "MetaCast";
	case EExprToken::EX_LetBool:              return "LetBool";
	case EExprToken::EX_EndParmValue:         return "EndParmValue";
	case EExprToken::EX_EndFunctionParms:     return "EndFunctionParms";
	case EExprToken::EX_Self:                 return "Self";
	case EExprToken::EX_Skip:                 return "Skip";
	case EExprToken::EX_Context:              return "Context";
	case EExprToken::EX_Context_FailSilent:   return "Context_FailSilent";
	case EExprToken::EX_VirtualFunction:      return "VirtualFunction";
	case EExprToken::EX_FinalFunction:        return "FinalFunction";
	case EExprToken::EX_IntConst:             return "IntConst";
	case EExprToken::EX_FloatConst:           return "FloatConst";
	case EExprToken::EX_StringConst:          return "StringConst";
	case EExprToken::EX_ObjectConst:          return "ObjectConst";
	case EExprToken::EX_NameConst:            return "NameConst";
	case EExprToken::EX_RotationConst:        return "RotationConst";
	case EExprToken::EX_VectorConst:          return "VectorConst";
	case EExprToken::EX_ByteConst:            return "ByteConst";
	case EExprToken::EX_IntZero:              return "IntZero";
	case EExprToken::EX_IntOne:               return "IntOne";
	case EExprToken::EX_True:                 return "True";
	case EExprToken::EX_False:                return "False";
	case EExprToken::EX_TextConst:            return "TextConst";
	case EExprToken::EX_NoObject:             return "NoObject";
	case EExprToken::EX_IntConstByte:         return "IntConstByte";
	case EExprToken::EX_NoInterface:          return "NoInterface";
	case EExprToken::EX_DynamicCast:          return "DynamicCast";
	case EExprToken::EX_StructConst:          return "StructConst";
	case EExprToken::EX_EndStructConst:       return "EndStructConst";
	case EExprToken::EX_SetArray:             return "SetArray";
	case EExprToken::EX_EndArray:             return "EndArray";
	case EExprToken::EX_UnicodeStringConst:   return "UnicodeStringConst";
	case EExprToken::EX_Int64Const:           return "Int64Const";
	case EExprToken::EX_UInt64Const:          return "UInt64Const";
	case EExprToken::EX_LetMulticastDelegate: return "LetMulticastDelegate";
	case EExprToken::EX_LetDelegate:          return "LetDelegate";
	case EExprToken::EX_LocalVirtualFunction: return "LocalVirtualFunction";
	case EExprToken::EX_LocalFinalFunction:   return "LocalFinalFunction";
	case EExprToken::EX_LocalOutVariable:     return "LocalOutVariable";
	case EExprToken::EX_InstanceDelegate:     return "InstanceDelegate";
	case EExprToken::EX_PushExecutionFlow:    return "PushExecutionFlow";
	case EExprToken::EX_PopExecutionFlow:     return "PopExecutionFlow";
	case EExprToken::EX_ComputedJump:         return "ComputedJump";
	case EExprToken::EX_PopExecutionFlowIfNot: return "PopExecutionFlowIfNot";
	case EExprToken::EX_Breakpoint:           return "Breakpoint";
	case EExprToken::EX_InterfaceContext:     return "InterfaceContext";
	case EExprToken::EX_ObjToInterfaceCast:   return "ObjToInterfaceCast";
	case EExprToken::EX_EndOfScript:          return "EndOfScript";
	case EExprToken::EX_CrossInterfaceCast:   return "CrossInterfaceCast";
	case EExprToken::EX_InterfaceToObjCast:   return "InterfaceToObjCast";
	case EExprToken::EX_AddMulticastDelegate: return "AddMulticastDelegate";
	case EExprToken::EX_ClearMulticastDelegate: return "ClearMulticastDelegate";
	case EExprToken::EX_LetObj:               return "LetObj";
	case EExprToken::EX_LetWeakObjPtr:        return "LetWeakObjPtr";
	case EExprToken::EX_BindDelegate:         return "BindDelegate";
	case EExprToken::EX_RemoveMulticastDelegate: return "RemoveMulticastDelegate";
	case EExprToken::EX_CallMulticastDelegate: return "CallMulticastDelegate";
	case EExprToken::EX_ArrayConst:           return "ArrayConst";
	case EExprToken::EX_EndArrayConst:        return "EndArrayConst";
	case EExprToken::EX_SoftObjectConst:      return "SoftObjectConst";
	case EExprToken::EX_CallMath:             return "CallMath";
	case EExprToken::EX_SwitchValue:          return "SwitchValue";
	case EExprToken::EX_ArrayGetByRef:        return "ArrayGetByRef";
	case EExprToken::EX_FieldPathConst:       return "FieldPathConst";
	default:                                  return "Unknown";
	}
}
