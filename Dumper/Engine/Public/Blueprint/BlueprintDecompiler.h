#pragma once

#include <string>
#include <vector>
#include <cstdint>
#include <functional>

#include "Blueprint/EExprToken.h"
#include "Unreal/UnrealObjects.h"

class BlueprintDecompiler
{
public:
	struct DecompileResult
	{
		std::string FunctionName;
		std::string ClassName;
		std::string FlagsString;
		int32_t ScriptSize;
		std::string Pseudocode;
	};

	// Decompile a single function's Script bytecode to pseudocode
	static DecompileResult Decompile(const UEFunction& Func);

	// Decompile raw bytecode bytes
	static std::string DecompileBytes(const std::vector<uint8_t>& Script);

private:
	// Bytecode stream reader
	class BytecodeReader
	{
	public:
		BytecodeReader(const std::vector<uint8_t>& InScript);

		bool HasMore() const;
		size_t GetPosition() const;
		size_t GetSize() const;

		uint8_t ReadByte();
		int32_t ReadInt32();
		int64_t ReadInt64();
		uint64_t ReadUInt64();
		float ReadFloat();
		double ReadDouble();
		uint16_t ReadUInt16();
		std::string ReadString();        // null-terminated ASCII
		std::string ReadUnicodeString();  // null-terminated UTF-16
		uint64_t ReadPointer();           // 8 bytes on 64-bit
		std::string ReadName();           // FScriptName (FName serialized)
		EExprToken PeekToken() const;
		EExprToken ReadToken();
		void Skip(size_t Count);

	private:
		const std::vector<uint8_t>& Script;
		size_t Position;
	};

	// Recursive expression parser - returns pseudocode string
	static std::string ParseExpression(BytecodeReader& Reader, int Depth = 0);

	// Parse function call arguments until EX_EndFunctionParms
	static std::string ParseCallArgs(BytecodeReader& Reader, int Depth);

	// Resolve a UObject pointer read from bytecode to a name
	static std::string ResolveObjectName(uint64_t Ptr);
};
