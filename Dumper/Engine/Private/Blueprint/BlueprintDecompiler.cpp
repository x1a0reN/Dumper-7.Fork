#include "Blueprint/BlueprintDecompiler.h"
#include "Unreal/ObjectArray.h"
#include "Platform.h"

#include <format>
#include <cstring>

// ============================================================
// BytecodeReader implementation
// ============================================================

BlueprintDecompiler::BytecodeReader::BytecodeReader(const std::vector<uint8_t>& InScript)
	: Script(InScript), Position(0)
{
}

bool BlueprintDecompiler::BytecodeReader::HasMore() const
{
	return Position < Script.size();
}

size_t BlueprintDecompiler::BytecodeReader::GetPosition() const
{
	return Position;
}

size_t BlueprintDecompiler::BytecodeReader::GetSize() const
{
	return Script.size();
}

uint8_t BlueprintDecompiler::BytecodeReader::ReadByte()
{
	if (Position >= Script.size()) return 0;
	return Script[Position++];
}

int32_t BlueprintDecompiler::BytecodeReader::ReadInt32()
{
	int32_t Value = 0;
	if (Position + 4 <= Script.size())
	{
		std::memcpy(&Value, &Script[Position], 4);
		Position += 4;
	}
	return Value;
}

int64_t BlueprintDecompiler::BytecodeReader::ReadInt64()
{
	int64_t Value = 0;
	if (Position + 8 <= Script.size())
	{
		std::memcpy(&Value, &Script[Position], 8);
		Position += 8;
	}
	return Value;
}

uint64_t BlueprintDecompiler::BytecodeReader::ReadUInt64()
{
	uint64_t Value = 0;
	if (Position + 8 <= Script.size())
	{
		std::memcpy(&Value, &Script[Position], 8);
		Position += 8;
	}
	return Value;
}

float BlueprintDecompiler::BytecodeReader::ReadFloat()
{
	float Value = 0.0f;
	if (Position + 4 <= Script.size())
	{
		std::memcpy(&Value, &Script[Position], 4);
		Position += 4;
	}
	return Value;
}

double BlueprintDecompiler::BytecodeReader::ReadDouble()
{
	double Value = 0.0;
	if (Position + 8 <= Script.size())
	{
		std::memcpy(&Value, &Script[Position], 8);
		Position += 8;
	}
	return Value;
}

uint16_t BlueprintDecompiler::BytecodeReader::ReadUInt16()
{
	uint16_t Value = 0;
	if (Position + 2 <= Script.size())
	{
		std::memcpy(&Value, &Script[Position], 2);
		Position += 2;
	}
	return Value;
}

std::string BlueprintDecompiler::BytecodeReader::ReadString()
{
	std::string Result;
	while (Position < Script.size())
	{
		char Ch = static_cast<char>(Script[Position++]);
		if (Ch == '\0') break;
		Result += Ch;
	}
	return Result;
}

std::string BlueprintDecompiler::BytecodeReader::ReadUnicodeString()
{
	std::string Result;
	while (Position + 1 < Script.size())
	{
		uint16_t Ch;
		std::memcpy(&Ch, &Script[Position], 2);
		Position += 2;
		if (Ch == 0) break;
		if (Ch < 128)
			Result += static_cast<char>(Ch);
		else
			Result += std::format("\\u{:04X}", Ch);
	}
	return Result;
}

uint64_t BlueprintDecompiler::BytecodeReader::ReadPointer()
{
	return ReadUInt64();
}

EExprToken BlueprintDecompiler::BytecodeReader::PeekToken() const
{
	if (Position >= Script.size()) return EExprToken::EX_EndOfScript;
	return static_cast<EExprToken>(Script[Position]);
}

EExprToken BlueprintDecompiler::BytecodeReader::ReadToken()
{
	return static_cast<EExprToken>(ReadByte());
}

void BlueprintDecompiler::BytecodeReader::Skip(size_t Count)
{
	Position += Count;
	if (Position > Script.size())
		Position = Script.size();
}

// ============================================================
// Helper: resolve UObject pointer to name
// ============================================================

std::string BlueprintDecompiler::ResolveObjectName(uint64_t Ptr)
{
	if (Ptr == 0)
		return "None";

	UEObject Obj(reinterpret_cast<void*>(Ptr));

	if (Platform::IsBadReadPtr(Obj.GetAddress()))
		return std::format("0x{:X}", Ptr);

	try
	{
		std::string Name = Obj.GetName();
		if (!Name.empty())
			return Name;
	}
	catch (...)
	{
	}

	return std::format("0x{:X}", Ptr);
}

// ============================================================
// Parse function call arguments until EX_EndFunctionParms
// ============================================================

std::string BlueprintDecompiler::ParseCallArgs(BytecodeReader& Reader, int Depth)
{
	std::string Args;
	bool bFirst = true;

	while (Reader.HasMore())
	{
		if (Reader.PeekToken() == EExprToken::EX_EndFunctionParms)
		{
			Reader.ReadToken(); // consume
			break;
		}

		if (!bFirst)
			Args += ", ";
		bFirst = false;

		Args += ParseExpression(Reader, Depth + 1);
	}

	return Args;
}

// ============================================================
// Core: recursive expression parser
// ============================================================

std::string BlueprintDecompiler::ParseExpression(BytecodeReader& Reader, int Depth)
{
	if (!Reader.HasMore() || Depth > 64)
		return "/* truncated */";

	const size_t Offset = Reader.GetPosition();
	const EExprToken Token = Reader.ReadToken();

	switch (Token)
	{
	// --- Constants ---
	case EExprToken::EX_IntConst:
		return std::to_string(Reader.ReadInt32());

	case EExprToken::EX_FloatConst:
		return std::format("{:.4f}f", Reader.ReadFloat());

	case EExprToken::EX_DoubleConst:
		return std::format("{:.6f}", Reader.ReadDouble());

	case EExprToken::EX_StringConst:
		return std::format("\"{}\"", Reader.ReadString());

	case EExprToken::EX_UnicodeStringConst:
		return std::format("L\"{}\"", Reader.ReadUnicodeString());

	case EExprToken::EX_ByteConst:
		return std::to_string(Reader.ReadByte());

	case EExprToken::EX_IntConstByte:
		return std::to_string(Reader.ReadByte());

	case EExprToken::EX_Int64Const:
		return std::to_string(Reader.ReadInt64()) + "LL";

	case EExprToken::EX_UInt64Const:
		return std::to_string(Reader.ReadUInt64()) + "ULL";

	case EExprToken::EX_IntZero:  return "0";
	case EExprToken::EX_IntOne:   return "1";
	case EExprToken::EX_True:     return "true";
	case EExprToken::EX_False:    return "false";
	case EExprToken::EX_NoObject: return "nullptr";
	case EExprToken::EX_NoInterface: return "nullptr";
	case EExprToken::EX_Self:     return "this";
	case EExprToken::EX_Nothing:  return "";

	// --- Variable references ---
	case EExprToken::EX_LocalVariable:
	case EExprToken::EX_LocalOutVariable:
	case EExprToken::EX_InstanceVariable:
	case EExprToken::EX_DefaultVariable:
	{
		uint64_t PropPtr = Reader.ReadPointer();
		return ResolveObjectName(PropPtr);
	}

	// --- Object/Name constants ---
	case EExprToken::EX_ObjectConst:
	{
		uint64_t ObjPtr = Reader.ReadPointer();
		return ResolveObjectName(ObjPtr);
	}

	case EExprToken::EX_NameConst:
	{
		// FScriptName: stored as FName (two int32s in bytecode)
		std::string Name = Reader.ReadString();
		return std::format("FName(\"{}\")", Name);
	}

	case EExprToken::EX_SoftObjectConst:
	{
		std::string Expr = ParseExpression(Reader, Depth + 1);
		return std::format("SoftObject({})", Expr);
	}

	// --- Function calls ---
	case EExprToken::EX_FinalFunction:
	case EExprToken::EX_LocalFinalFunction:
	{
		uint64_t FuncPtr = Reader.ReadPointer();
		std::string FuncName = ResolveObjectName(FuncPtr);
		std::string Args = ParseCallArgs(Reader, Depth);
		return std::format("{}({})", FuncName, Args);
	}

	case EExprToken::EX_VirtualFunction:
	case EExprToken::EX_LocalVirtualFunction:
	{
		std::string FuncName = Reader.ReadString();
		std::string Args = ParseCallArgs(Reader, Depth);
		return std::format("{}({})", FuncName, Args);
	}

	case EExprToken::EX_CallMath:
	{
		uint64_t FuncPtr = Reader.ReadPointer();
		std::string FuncName = ResolveObjectName(FuncPtr);
		std::string Args = ParseCallArgs(Reader, Depth);
		return std::format("Math::{}({})", FuncName, Args);
	}

	case EExprToken::EX_CallMulticastDelegate:
	{
		uint64_t FuncPtr = Reader.ReadPointer();
		std::string FuncName = ResolveObjectName(FuncPtr);
		std::string Args = ParseCallArgs(Reader, Depth);
		return std::format("{}.Broadcast({})", FuncName, Args);
	}

	// --- Assignment ---
	case EExprToken::EX_Let:
	case EExprToken::EX_LetBool:
	case EExprToken::EX_LetObj:
	case EExprToken::EX_LetWeakObjPtr:
	case EExprToken::EX_LetDelegate:
	case EExprToken::EX_LetMulticastDelegate:
	{
		uint64_t PropPtr = Reader.ReadPointer();
		std::string VarExpr = ParseExpression(Reader, Depth + 1);
		std::string ValueExpr = ParseExpression(Reader, Depth + 1);
		return std::format("{} = {}", VarExpr, ValueExpr);
	}

	// --- Control flow ---
	case EExprToken::EX_Jump:
	{
		uint32_t TargetOffset = static_cast<uint32_t>(Reader.ReadInt32());
		return std::format("goto 0x{:04X}", TargetOffset);
	}

	case EExprToken::EX_JumpIfNot:
	{
		uint32_t TargetOffset = static_cast<uint32_t>(Reader.ReadInt32());
		std::string Condition = ParseExpression(Reader, Depth + 1);
		return std::format("if (!{}) goto 0x{:04X}", Condition, TargetOffset);
	}

	case EExprToken::EX_Return:
	{
		std::string RetExpr = ParseExpression(Reader, Depth + 1);
		if (RetExpr.empty())
			return "return";
		return std::format("return {}", RetExpr);
	}

	case EExprToken::EX_PushExecutionFlow:
	{
		uint32_t TargetOffset = static_cast<uint32_t>(Reader.ReadInt32());
		return std::format("/* push flow 0x{:04X} */", TargetOffset);
	}

	case EExprToken::EX_PopExecutionFlow:
		return "/* pop flow */";

	case EExprToken::EX_PopExecutionFlowIfNot:
	{
		std::string Condition = ParseExpression(Reader, Depth + 1);
		return std::format("/* pop flow if !{} */", Condition);
	}

	case EExprToken::EX_ComputedJump:
	{
		std::string Expr = ParseExpression(Reader, Depth + 1);
		return std::format("goto [{}]", Expr);
	}

	// --- Context (object.member) ---
	case EExprToken::EX_Context:
	case EExprToken::EX_Context_FailSilent:
	{
		std::string ObjExpr = ParseExpression(Reader, Depth + 1);
		Reader.Skip(4 + 1); // SkipOffset (4) + PropertyType (1)
		uint64_t PropPtr = Reader.ReadPointer();
		std::string MemberExpr = ParseExpression(Reader, Depth + 1);
		return std::format("{}.{}", ObjExpr, MemberExpr);
	}

	case EExprToken::EX_ClassContext:
	{
		std::string ObjExpr = ParseExpression(Reader, Depth + 1);
		Reader.Skip(4 + 1);
		uint64_t PropPtr = Reader.ReadPointer();
		std::string MemberExpr = ParseExpression(Reader, Depth + 1);
		return std::format("{}::{}", ObjExpr, MemberExpr);
	}

	case EExprToken::EX_InterfaceContext:
	{
		std::string Expr = ParseExpression(Reader, Depth + 1);
		return Expr;
	}

	// --- Casts ---
	case EExprToken::EX_DynamicCast:
	case EExprToken::EX_ObjToInterfaceCast:
	case EExprToken::EX_CrossInterfaceCast:
	case EExprToken::EX_InterfaceToObjCast:
	{
		uint64_t ClassPtr = Reader.ReadPointer();
		std::string ClassName = ResolveObjectName(ClassPtr);
		std::string Expr = ParseExpression(Reader, Depth + 1);
		return std::format("Cast<{}>({})", ClassName, Expr);
	}

	case EExprToken::EX_MetaCast:
	{
		uint64_t ClassPtr = Reader.ReadPointer();
		std::string ClassName = ResolveObjectName(ClassPtr);
		std::string Expr = ParseExpression(Reader, Depth + 1);
		return std::format("MetaCast<{}>({})", ClassName, Expr);
	}

	// --- Vector/Rotation/Transform constants ---
	case EExprToken::EX_VectorConst:
	{
		float X = Reader.ReadFloat(), Y = Reader.ReadFloat(), Z = Reader.ReadFloat();
		return std::format("FVector({:.2f}, {:.2f}, {:.2f})", X, Y, Z);
	}

	case EExprToken::EX_RotationConst:
	{
		float P = Reader.ReadFloat(), Y = Reader.ReadFloat(), R = Reader.ReadFloat();
		return std::format("FRotator({:.2f}, {:.2f}, {:.2f})", P, Y, R);
	}

	case EExprToken::EX_TransformConst:
	{
		// Rotation (quat: 4 floats) + Translation (3 floats) + Scale (3 floats)
		Reader.Skip(4 * 10);
		return "FTransform(...)";
	}

	// --- Struct constant ---
	case EExprToken::EX_StructConst:
	{
		uint64_t StructPtr = Reader.ReadPointer();
		int32_t StructSize = Reader.ReadInt32();
		std::string StructName = ResolveObjectName(StructPtr);
		std::string Fields;
		bool bFirst = true;
		while (Reader.HasMore() && Reader.PeekToken() != EExprToken::EX_EndStructConst)
		{
			if (!bFirst) Fields += ", ";
			bFirst = false;
			Fields += ParseExpression(Reader, Depth + 1);
		}
		if (Reader.HasMore()) Reader.ReadToken(); // consume EndStructConst
		return std::format("{}{{ {} }}", StructName, Fields);
	}

	// --- Delegate ---
	case EExprToken::EX_InstanceDelegate:
	case EExprToken::EX_BindDelegate:
	{
		std::string FuncName = Reader.ReadString();
		std::string Obj = ParseExpression(Reader, Depth + 1);
		return std::format("Delegate({}, {})", FuncName, Obj);
	}

	case EExprToken::EX_AddMulticastDelegate:
	{
		std::string Delegate = ParseExpression(Reader, Depth + 1);
		std::string Func = ParseExpression(Reader, Depth + 1);
		return std::format("{}.Add({})", Delegate, Func);
	}

	case EExprToken::EX_RemoveMulticastDelegate:
	{
		std::string Delegate = ParseExpression(Reader, Depth + 1);
		std::string Func = ParseExpression(Reader, Depth + 1);
		return std::format("{}.Remove({})", Delegate, Func);
	}

	case EExprToken::EX_ClearMulticastDelegate:
	{
		std::string Delegate = ParseExpression(Reader, Depth + 1);
		return std::format("{}.Clear()", Delegate);
	}

	// --- Skip / Assert ---
	case EExprToken::EX_Skip:
	{
		uint32_t SkipSize = static_cast<uint32_t>(Reader.ReadInt32());
		std::string Expr = ParseExpression(Reader, Depth + 1);
		return Expr;
	}

	case EExprToken::EX_SkipOffsetConst:
	{
		uint32_t Val = static_cast<uint32_t>(Reader.ReadInt32());
		return std::format("/* skip offset 0x{:04X} */", Val);
	}

	case EExprToken::EX_Assert:
	{
		uint16_t LineNum = Reader.ReadUInt16();
		uint8_t InDebug = Reader.ReadByte();
		std::string Expr = ParseExpression(Reader, Depth + 1);
		return std::format("assert({})", Expr);
	}

	// --- Array ---
	case EExprToken::EX_SetArray:
	{
		std::string ArrayExpr = ParseExpression(Reader, Depth + 1);
		std::string Elements;
		bool bFirst = true;
		while (Reader.HasMore() && Reader.PeekToken() != EExprToken::EX_EndArray)
		{
			if (!bFirst) Elements += ", ";
			bFirst = false;
			Elements += ParseExpression(Reader, Depth + 1);
		}
		if (Reader.HasMore()) Reader.ReadToken();
		return std::format("{} = [{}]", ArrayExpr, Elements);
	}

	case EExprToken::EX_ArrayGetByRef:
	{
		std::string ArrayExpr = ParseExpression(Reader, Depth + 1);
		std::string IndexExpr = ParseExpression(Reader, Depth + 1);
		return std::format("{}[{}]", ArrayExpr, IndexExpr);
	}

	// --- SwitchValue ---
	case EExprToken::EX_SwitchValue:
	{
		uint16_t NumCases = Reader.ReadUInt16();
		uint32_t EndOffset = static_cast<uint32_t>(Reader.ReadInt32());
		std::string IndexExpr = ParseExpression(Reader, Depth + 1);
		std::string Result = std::format("switch ({}) {{ ", IndexExpr);
		for (int i = 0; i < NumCases; i++)
		{
			std::string CaseVal = ParseExpression(Reader, Depth + 1);
			uint32_t CaseOffset = static_cast<uint32_t>(Reader.ReadInt32());
			std::string CaseExpr = ParseExpression(Reader, Depth + 1);
			Result += std::format("case {}: {}; ", CaseVal, CaseExpr);
		}
		std::string DefaultExpr = ParseExpression(Reader, Depth + 1);
		Result += std::format("default: {} }}", DefaultExpr);
		return Result;
	}

	// --- TextConst ---
	case EExprToken::EX_TextConst:
	{
		uint8_t TextType = Reader.ReadByte();
		// Simplified: just read sub-expressions based on type
		switch (TextType)
		{
		case 0: // Empty
			return "FText::GetEmpty()";
		case 1: // LocalizedText
		{
			std::string Src = ParseExpression(Reader, Depth + 1);
			std::string Key = ParseExpression(Reader, Depth + 1);
			std::string Ns = ParseExpression(Reader, Depth + 1);
			return std::format("NSLOCTEXT({}, {}, {})", Ns, Key, Src);
		}
		case 2: // InvariantCultureText
		{
			std::string Src = ParseExpression(Reader, Depth + 1);
			return std::format("FText::AsCultureInvariant({})", Src);
		}
		default:
			return "FText(...)";
		}
	}

	case EExprToken::EX_StructMemberContext:
	{
		uint64_t PropPtr = Reader.ReadPointer();
		std::string PropName = ResolveObjectName(PropPtr);
		std::string StructExpr = ParseExpression(Reader, Depth + 1);
		return std::format("{}.{}", StructExpr, PropName);
	}

	case EExprToken::EX_EndOfScript:
		return "";

	case EExprToken::EX_EndFunctionParms:
	case EExprToken::EX_EndStructConst:
	case EExprToken::EX_EndArray:
	case EExprToken::EX_EndArrayConst:
		return "";

	default:
		return std::format("/* unknown opcode 0x{:02X} */", static_cast<uint8_t>(Token));
	}
}

// ============================================================
// Top-level: decompile raw bytes to pseudocode
// ============================================================

std::string BlueprintDecompiler::DecompileBytes(const std::vector<uint8_t>& Script)
{
	if (Script.empty())
		return "// Empty script\n";

	BytecodeReader Reader(Script);
	std::string Output;
	int LineNum = 0;

	while (Reader.HasMore())
	{
		if (Reader.PeekToken() == EExprToken::EX_EndOfScript)
			break;

		if (Reader.PeekToken() == EExprToken::EX_Nothing)
		{
			Reader.ReadToken();
			continue;
		}

		const size_t Offset = Reader.GetPosition();
		std::string Expr = ParseExpression(Reader, 0);

		if (!Expr.empty())
		{
			Output += std::format("  {:04X}: {}\n", Offset, Expr);
			LineNum++;
		}

		// Safety: prevent infinite loops
		if (LineNum > 2000)
		{
			Output += "  // ... truncated (>2000 statements)\n";
			break;
		}
	}

	return Output;
}

// ============================================================
// Top-level: decompile a UEFunction
// ============================================================

BlueprintDecompiler::DecompileResult BlueprintDecompiler::Decompile(const UEFunction& Func)
{
	DecompileResult Result;
	Result.FunctionName = Func.GetName();
	Result.ClassName = Func.GetOuter().GetName();
	Result.FlagsString = Func.StringifyFlags();
	Result.ScriptSize = Func.GetScriptSize();

	std::vector<uint8_t> Script = Func.GetScript();
	Result.Pseudocode = DecompileBytes(Script);

	return Result;
}
