#include "Generators/DumpspaceGenerator.h"
#include "Generators/EmbeddedIdaScript.h"
#include "Generators/Generator.h"

#include "Platform.h"
#include "OffsetFinder/Offsets.h"

#include <fstream>

std::string DumpspaceGenerator::GetStructPrefixedName(const StructWrapper& Struct)
{
	if (Struct.IsFunction())
		return Struct.GetUnrealStruct().GetOuter().GetValidName() + "_" + Struct.GetName();

	auto [ValidName, bIsUnique] = Struct.GetUniqueName();

	if (bIsUnique) [[likely]]
		return ValidName;

	/* Package::FStructName */
	return PackageManager::GetName(Struct.GetUnrealStruct().GetPackageIndex()) + "::" + ValidName;
}

std::string DumpspaceGenerator::GetEnumPrefixedName(const EnumWrapper& Enum)
{
	auto [ValidName, bIsUnique] = Enum.GetUniqueName();

	if (bIsUnique) [[likely]]
		return ValidName;

	/* Package::ESomeEnum */
	return PackageManager::GetName(Enum.GetUnrealEnum().GetPackageIndex()) + "::" + ValidName;
}

std::string DumpspaceGenerator::EnumSizeToType(const int32 Size)
{
	static constexpr std::array<const char*, 8> UnderlayingTypesBySize = {
		"uint8",
		"uint16",
		"InvalidEnumSize",
		"uint32",
		"InvalidEnumSize",
		"InvalidEnumSize",
		"InvalidEnumSize",
		"uint64"
	};

	return Size <= 0x8 ? UnderlayingTypesBySize[static_cast<size_t>(Size) - 1] : "uint8";
}

DSGen::EType DumpspaceGenerator::GetMemberEType(const PropertyWrapper& Property)
{
	/* Predefined members are currently not supported by DumpspaceGenerator */
	if (!Property.IsUnrealProperty())
		return DSGen::ET_Default;

	return GetMemberEType(Property.GetUnrealProperty());
}

DSGen::EType DumpspaceGenerator::GetMemberEType(UEProperty Prop)
{
	if (Prop.IsA(EClassCastFlags::EnumProperty))
	{
		return DSGen::ET_Enum;
	}
	else if (Prop.IsA(EClassCastFlags::ByteProperty))
	{
		if (Prop.Cast<UEByteProperty>().GetEnum())
			return DSGen::ET_Enum;
	}
	//else if (Prop.IsA(EClassCastFlags::ClassProperty))
	//{
	//	/* Check if this is a UClass*, not TSubclassof<UObject> */
	//	if (!Prop.Cast<UEClassProperty>().HasPropertyFlags(EPropertyFlags::UObjectWrapper))
	//		return DSGen::ET_Class; 
	//}
	else if (Prop.IsA(EClassCastFlags::ObjectProperty))
	{
		return DSGen::ET_Class;
	}
	else if (Prop.IsA(EClassCastFlags::StructProperty))
	{
		return DSGen::ET_Struct;
	}
	else if (Prop.IsType(EClassCastFlags::ArrayProperty | EClassCastFlags::MapProperty | EClassCastFlags::SetProperty))
	{
		return DSGen::ET_Class;
	}

	return DSGen::ET_Default;
}

std::string DumpspaceGenerator::GetMemberTypeStr(UEProperty Property, std::string& OutExtendedType, std::vector<DSGen::MemberType>& OutSubtypes)
{
	UEProperty Member = Property;

	auto [Class, FieldClass] = Member.GetClass();

	EClassCastFlags Flags = Class ? Class.GetCastFlags() : FieldClass.GetCastFlags();

	if (Flags & EClassCastFlags::ByteProperty)
	{
		if (UEEnum Enum = Member.Cast<UEByteProperty>().GetEnum())
			return GetEnumPrefixedName(Enum);

		return "uint8";
	}
	else if (Flags & EClassCastFlags::UInt16Property)
	{
		return "uint16";
	}
	else if (Flags & EClassCastFlags::UInt32Property)
	{
		return "uint32";
	}
	else if (Flags & EClassCastFlags::UInt64Property)
	{
		return "uint64";
	}
	else if (Flags & EClassCastFlags::Int8Property)
	{
		return "int8";
	}
	else if (Flags & EClassCastFlags::Int16Property)
	{
		return "int16";
	}
	else if (Flags & EClassCastFlags::IntProperty)
	{
		return "int32";
	}
	else if (Flags & EClassCastFlags::Int64Property)
	{
		return "int64";
	}
	else if (Flags & EClassCastFlags::FloatProperty)
	{
		return "float";
	}
	else if (Flags & EClassCastFlags::DoubleProperty)
	{
		return "double";
	}
	else if (Flags & EClassCastFlags::ClassProperty)
	{
		if (Member.HasPropertyFlags(EPropertyFlags::UObjectWrapper))
		{
			OutSubtypes.emplace_back(GetMemberType(Member.Cast<UEClassProperty>().GetMetaClass()));

			return "TSubclassOf";
		}

		OutExtendedType = "*";

		return "UClass";
	}
	else if (Flags & EClassCastFlags::NameProperty)
	{
		return "FName";
	}
	else if (Flags & EClassCastFlags::StrProperty)
	{
		return "FString";
	}
	else if (Flags & EClassCastFlags::TextProperty)
	{
		return "FText";
	}
	else if (Flags & EClassCastFlags::BoolProperty)
	{
		return Member.Cast<UEBoolProperty>().IsNativeBool() ? "bool" : "uint8";
	}
	else if (Flags & EClassCastFlags::StructProperty)
	{
		const StructWrapper& UnderlayingStruct = Member.Cast<UEStructProperty>().GetUnderlayingStruct();

		return GetStructPrefixedName(UnderlayingStruct);
	}
	else if (Flags & EClassCastFlags::ArrayProperty)
	{
		OutSubtypes.push_back(GetMemberType(Member.Cast<UEArrayProperty>().GetInnerProperty()));

		return "TArray";
	}
	else if (Flags & EClassCastFlags::WeakObjectProperty)
	{
		if (UEClass PropertyClass = Member.Cast<UEWeakObjectProperty>().GetPropertyClass()) 
		{
			OutSubtypes.push_back(GetMemberType(PropertyClass));
		}
		else
		{
			OutSubtypes.push_back(ManualCreateMemberType(DSGen::ET_Class, "UObject"));
		}

		return "TWeakObjectPtr";
	}
	else if (Flags & EClassCastFlags::LazyObjectProperty)
	{
		if (UEClass PropertyClass = Member.Cast<UELazyObjectProperty>().GetPropertyClass())
		{
			OutSubtypes.push_back(GetMemberType(PropertyClass));
		}
		else
		{
			OutSubtypes.push_back(ManualCreateMemberType(DSGen::ET_Class, "UObject"));
		}

		return "TLazyObjectPtr";
	}
	else if (Flags & EClassCastFlags::SoftClassProperty)
	{
		if (UEClass PropertyClass = Member.Cast<UESoftClassProperty>().GetPropertyClass())
		{
			OutSubtypes.push_back(GetMemberType(PropertyClass));
		}
		else
		{
			OutSubtypes.push_back(ManualCreateMemberType(DSGen::ET_Class, "UClass"));
		}

		return "TSoftClassPtr";
	}
	else if (Flags & EClassCastFlags::SoftObjectProperty)
	{
		if (UEClass PropertyClass = Member.Cast<UESoftObjectProperty>().GetPropertyClass())
		{
			OutSubtypes.push_back(GetMemberType(PropertyClass));
		}
		else
		{
			OutSubtypes.push_back(ManualCreateMemberType(DSGen::ET_Class, "UObject"));
		}

		return "TSoftObjectPtr";
	}
	else if (Flags & EClassCastFlags::ObjectProperty)
	{
		OutExtendedType = "*";

		if (UEClass PropertyClass = Member.Cast<UEObjectProperty>().GetPropertyClass())
			return GetStructPrefixedName(PropertyClass);
		
		return "UObject";
	}
	else if (Settings::EngineCore::bEnableEncryptedObjectPropertySupport && Flags & EClassCastFlags::ObjectPropertyBase && Member.GetSize() == 0x10)
	{
		if (UEClass PropertyClass = Member.Cast<UEObjectProperty>().GetPropertyClass())
			return std::format("TEncryptedObjPtr<class {}>", GetStructPrefixedName(PropertyClass));

		return "TEncryptedObjPtr<class UObject>";
	}
	else if (Flags & EClassCastFlags::MapProperty)
	{
		UEMapProperty MemberAsMapProperty = Member.Cast<UEMapProperty>();

		OutSubtypes.emplace_back(GetMemberType(Member.Cast<UEMapProperty>().GetKeyProperty()));
		OutSubtypes.emplace_back(GetMemberType(Member.Cast<UEMapProperty>().GetValueProperty()));

		return "TMap";
	}
	else if (Flags & EClassCastFlags::SetProperty)
	{
		OutSubtypes.emplace_back(GetMemberType(Member.Cast<UESetProperty>().GetElementProperty()));

		return "TSet";
	}
	else if (Flags & EClassCastFlags::EnumProperty)
	{
		if (UEEnum Enum = Member.Cast<UEEnumProperty>().GetEnum())
			return GetEnumPrefixedName(Enum);

		return "NamelessEnumIGuessIdkWhatToPutHereWithRegardsTheGuyFromDumper7";
	}
	else if (Flags & EClassCastFlags::InterfaceProperty)
	{
		if (UEClass PropertyClass = Member.Cast<UEInterfaceProperty>().GetPropertyClass())
		{
			OutSubtypes.push_back(GetMemberType(PropertyClass));
		}
		else
		{
			OutSubtypes.push_back(ManualCreateMemberType(DSGen::ET_Class, "IInterface"));
		}

		return "TScriptInterface";
	}
	else if (Flags & EClassCastFlags::FieldPathProperty)
	{

		if (Settings::Internal::bIsObjPtrInsteadOfFieldPathProperty)
		{
			OutExtendedType = "*";

			if (UEClass PropertyClass = Member.Cast<UEObjectProperty>().GetPropertyClass())
				return GetStructPrefixedName(PropertyClass);

			return "UObject";
		}

		if (UEFFieldClass PropertyClass = Member.Cast<UEFieldPathProperty>().GetFieldClass())
		{
			OutSubtypes.push_back(ManualCreateMemberType(DSGen::ET_Struct, PropertyClass.GetCppName()));
		}
		else
		{
			OutSubtypes.push_back(ManualCreateMemberType(DSGen::ET_Struct, "FField"));
		}

		return "TFieldPath";
	}
	else if (Flags & EClassCastFlags::OptionalProperty)
	{
		UEProperty ValueProperty = Member.Cast<UEOptionalProperty>().GetValueProperty();

		OutSubtypes.push_back(GetMemberType(ValueProperty));

		return "TOptional";
	}
	else
	{
		/* When changing this also change 'GetUnknownProperties()' */
		return (Class ? Class.GetCppName() : FieldClass.GetCppName()) + "_";
	}
}

DSGen::MemberType DumpspaceGenerator::GetMemberType(const StructWrapper& Struct)
{
	DSGen::MemberType Type;
	Type.type = Struct.IsClass() ? DSGen::ET_Class : DSGen::ET_Struct;
	Type.typeName = GetStructPrefixedName(Struct);
	Type.extendedType = Struct.IsClass() ? "*" : "";
	Type.reference = false;

	return Type;
}

DSGen::MemberType DumpspaceGenerator::GetMemberType(const PropertyWrapper& Property, bool bIsReference)
{
	DSGen::MemberType Type;

	if (!Property.IsUnrealProperty())
	{
		Type.typeName = "Unsupported_Predefined_Member";
		return Type;
	}

	Type.reference = bIsReference;
	Type.type = GetMemberEType(Property);
	Type.typeName = GetMemberTypeStr(Property.GetUnrealProperty(), Type.extendedType, Type.subTypes);

	return Type;
}

DSGen::MemberType DumpspaceGenerator::GetMemberType(UEProperty Property, bool bIsReference)
{
	DSGen::MemberType Type;

	Type.reference = bIsReference;
	Type.type = GetMemberEType(Property);
	Type.typeName = GetMemberTypeStr(Property, Type.extendedType, Type.subTypes);

	return Type;
}

DSGen::MemberType DumpspaceGenerator::ManualCreateMemberType(DSGen::EType Type, const std::string& TypeName, const std::string& ExtendedType)
{
	return DSGen::createMemberType(Type, TypeName, ExtendedType);
}

void DumpspaceGenerator::AddMemberToStruct(DSGen::ClassHolder& Struct, const PropertyWrapper& Property)
{
	DSGen::MemberDefinition Member;
	Member.memberType = GetMemberType(Property);
	Member.bitOffset = Property.IsBitField() ? Property.GetBitIndex() : -1;
	Member.offset = Property.GetOffset();
	Member.size = Property.GetSize() * Property.GetArrayDim();
	Member.memberName = Property.GetName();
	Member.arrayDim = Property.GetArrayDim();

	Struct.members.push_back(std::move(Member));
}

void DumpspaceGenerator::RecursiveGetSuperClasses(const StructWrapper& Struct, std::vector<std::string>& OutSupers)
{
	const StructWrapper& Super = Struct.GetSuper();

	OutSupers.push_back(Struct.GetUniqueName().first);

	if (Super.IsValid())
		RecursiveGetSuperClasses(Super, OutSupers);
}

std::vector<std::string> DumpspaceGenerator::GetSuperClasses(const StructWrapper& Struct)
{
	std::vector<std::string> RetSuperNames;

	const StructWrapper& Super = Struct.GetSuper();

	if (Super.IsValid())
		RecursiveGetSuperClasses(Super, RetSuperNames);

	return RetSuperNames;
}

DSGen::ClassHolder DumpspaceGenerator::GenerateStruct(const StructWrapper& Struct)
{
	DSGen::ClassHolder StructOrClass;
	StructOrClass.className = GetStructPrefixedName(Struct);
	StructOrClass.classSize = Struct.GetSize();
	StructOrClass.classType = Struct.IsClass() ? DSGen::ET_Class : DSGen::ET_Struct;
	StructOrClass.interitedTypes = GetSuperClasses(Struct);

	MemberManager Members = Struct.GetMembers();

	for (const PropertyWrapper& Wrapper : Members.IterateMembers())
		AddMemberToStruct(StructOrClass, Wrapper);

	if (!Struct.IsClass())
		return StructOrClass;

	for (const FunctionWrapper& Wrapper : Members.IterateFunctions())
		StructOrClass.functions.push_back(GenearateFunction(Wrapper));

	return StructOrClass;
}

DSGen::EnumHolder DumpspaceGenerator::GenerateEnum(const EnumWrapper& Enum)
{
	DSGen::EnumHolder Enumerator;
	Enumerator.enumName = GetEnumPrefixedName(Enum);
	Enumerator.enumType = EnumSizeToType(Enum.GetUnderlyingTypeSize());

	Enumerator.enumMembers.reserve(Enum.GetNumMembers());
		
	for (const EnumCollisionInfo& Info : Enum.GetMembers())
		Enumerator.enumMembers.emplace_back(Info.GetUniqueName(), Info.GetValue());

	return Enumerator;
}

DSGen::FunctionHolder DumpspaceGenerator::GenearateFunction(const FunctionWrapper& Function)
{
	DSGen::FunctionHolder RetFunc;

	StructWrapper FuncAsStruct = Function.AsStruct();
	MemberManager FuncParams = FuncAsStruct.GetMembers();

	RetFunc.functionName = Function.GetName();
	RetFunc.functionOffset = Function.GetExecFuncOffset();
	RetFunc.functionFlags = Function.StringifyFlags("|");
	RetFunc.returnType = ManualCreateMemberType(DSGen::ET_Default, "void");

	for (const PropertyWrapper& Param : FuncParams.IterateMembers())
	{
		if (!Param.HasPropertyFlags(EPropertyFlags::Parm))
			continue;

		if (Param.HasPropertyFlags(EPropertyFlags::ReturnParm))
		{
			RetFunc.returnType = GetMemberType(Param);
			continue;
		}

		RetFunc.functionParams.emplace_back(GetMemberType(Param), Param.GetName());
	}

	return RetFunc;
}

void DumpspaceGenerator::GeneratedStaticOffsets()
{
	DSGen::addOffset("Dumper", 7);

	DSGen::addOffset("OFFSET_GOBJECTS", Off::InSDK::ObjArray::GObjects);
	DSGen::addOffset(Off::InSDK::Name::bIsUsingAppendStringOverToString ? "OFFSET_APPENDSTRING" : "OFFSET_TOSTRING", Off::InSDK::Name::AppendNameToString);
	DSGen::addOffset("OFFSET_GNAMES", Off::InSDK::NameArray::GNames);
	DSGen::addOffset("OFFSET_GWORLD", Off::InSDK::World::GWorld);
	if (Off::InSDK::Engine::GEngine != 0x0)
		DSGen::addOffset("OFFSET_GENGINE", Off::InSDK::Engine::GEngine);
	DSGen::addOffset("OFFSET_PROCESSEVENT", Off::InSDK::ProcessEvent::PEOffset);
	DSGen::addOffset("INDEX_PROCESSEVENT", Off::InSDK::ProcessEvent::PEIndex);

	if (Off::InSDK::PostRender::GVCPostRenderIndex >= 0)
		DSGen::addOffset("INDEX_GVC_POSTRENDER", Off::InSDK::PostRender::GVCPostRenderIndex);
	if (Off::InSDK::PostRender::HUDPostRenderIndex >= 0)
		DSGen::addOffset("INDEX_HUD_POSTRENDER", Off::InSDK::PostRender::HUDPostRenderIndex);
}

void DumpspaceGenerator::GenerateVTableInfo(const fs::path& OutputDir)
{
	static const char* TargetClasses[] = {
		"Object", "Actor", "Pawn", "Character",
		"PlayerController", "GameViewportClient", "HUD",
		"GameEngine", "World", "GameInstance",
		"PlayerState", "GameStateBase", "GameModeBase"
	};

	std::ofstream Out(OutputDir / "VTableInfo.json");
	if (!Out.is_open())
	{
		std::cerr << "VTableInfo: Failed to create output file.\n";
		return;
	}

	Out << "{\n  \"data\": {\n";

	bool bFirstClass = true;

	for (const char* ClassName : TargetClasses)
	{
		UEClass TargetClass = ObjectArray::FindClassFast(ClassName);
		if (!TargetClass)
			continue;

		UEObject CDO = TargetClass.GetDefaultObject();
		if (!CDO)
			continue;

		void** Vft = *reinterpret_cast<void***>(CDO.GetAddress());
		if (!Vft || Platform::IsBadReadPtr(Vft))
			continue;

		// Count valid vtable entries
		int32 VTableCount = 0;
		for (int32 i = 0; i < 1024; i++)
		{
			if (Platform::IsBadReadPtr(&Vft[i]))
				break;

			void* Entry = Vft[i];
			if (!Entry || !Platform::IsAddressInProcessRange(Entry))
				break;

			VTableCount++;
		}

		if (VTableCount == 0)
			continue;

		if (!bFirstClass)
			Out << ",\n";
		bFirstClass = false;

		Out << "    \"" << ClassName << "\": {\n";
		Out << "      \"vtable_count\": " << VTableCount << ",\n";
		Out << "      \"entries\": [";

		for (int32 i = 0; i < VTableCount; i++)
		{
			uintptr_t Rva = Platform::GetOffset(Vft[i]);

			if (i > 0)
				Out << ", ";
			if (i % 8 == 0)
				Out << "\n        ";

			Out << "[" << i << ", " << Rva << "]";
		}

		Out << "\n      ]\n    }";

		std::cerr << std::format("VTable: {} - {} entries\n", ClassName, VTableCount);
	}

	Out << "\n  }\n}\n";
	Out.close();

	std::cerr << "VTableInfo.json generated.\n\n";
}

void DumpspaceGenerator::GenerateCESymbols(const fs::path& OutputDir)
{
	std::ofstream Lua(OutputDir / "ce_symbols.lua");
	if (!Lua.is_open())
	{
		std::cerr << "CE Symbols: Failed to create ce_symbols.lua\n";
		return;
	}

	Lua << "-- Dumper-7 CE Symbol Pack\n";
	Lua << "-- Auto-generated. Execute this script in Cheat Engine to load all symbols.\n";
	Lua << "-- Provides: global offsets, vtable functions, reflected functions, structures, enums\n\n";
	Lua << "local base = getAddress(process)\n";
	Lua << "local symCount = 0\n\n";

	Lua << "local function reg(name, addr)\n";
	Lua << "  registerSymbol(name, addr, true)\n";
	Lua << "  symCount = symCount + 1\n";
	Lua << "end\n\n";

	// ============ Section 1: Global Offsets ============
	Lua << "-- ============ Global Offsets ============\n";
	Lua << std::format("reg(\"GObjects\", base + 0x{:X})\n", Off::InSDK::ObjArray::GObjects);
	Lua << std::format("reg(\"GNames\", base + 0x{:X})\n", Off::InSDK::NameArray::GNames);
	Lua << std::format("reg(\"GWorld\", base + 0x{:X})\n", Off::InSDK::World::GWorld);
	if (Off::InSDK::Engine::GEngine != 0x0)
		Lua << std::format("reg(\"GEngine\", base + 0x{:X})\n", Off::InSDK::Engine::GEngine);
	Lua << std::format("reg(\"ProcessEvent\", base + 0x{:X})\n", Off::InSDK::ProcessEvent::PEOffset);
	if (Off::InSDK::Name::bIsUsingAppendStringOverToString)
		Lua << std::format("reg(\"FName_AppendString\", base + 0x{:X})\n", Off::InSDK::Name::AppendNameToString);
	else
		Lua << std::format("reg(\"FName_ToString\", base + 0x{:X})\n", Off::InSDK::Name::AppendNameToString);
	Lua << "\n";

	// ============ Section 2: VTable Symbols ============
	Lua << "-- ============ VTable Symbols ============\n";
	{
		static const char* VTableClasses[] = {
			"Object", "Actor", "Pawn", "Character",
			"PlayerController", "GameViewportClient", "HUD",
			"GameEngine", "World", "GameInstance",
			"PlayerState", "GameStateBase", "GameModeBase"
		};

		int32 VTableSymCount = 0;

		for (const char* ClassName : VTableClasses)
		{
			UEClass TargetClass = ObjectArray::FindClassFast(ClassName);
			if (!TargetClass)
				continue;

			UEObject CDO = TargetClass.GetDefaultObject();
			if (!CDO)
				continue;

			void** Vft = *reinterpret_cast<void***>(CDO.GetAddress());
			if (!Vft || Platform::IsBadReadPtr(Vft))
				continue;

			Lua << "-- " << ClassName << " vtable\n";

			for (int32 i = 0; i < 1024; i++)
			{
				if (Platform::IsBadReadPtr(&Vft[i]))
					break;

				void* Entry = Vft[i];
				if (!Entry || !Platform::IsAddressInProcessRange(Entry))
					break;

				uintptr_t Rva = Platform::GetOffset(Entry);
				Lua << std::format("reg(\"{}::vfunc_{}\", base + 0x{:X})\n", ClassName, i, Rva);
				VTableSymCount++;
			}

			Lua << "\n";
		}

		std::cerr << std::format("CE Symbols: {} vtable symbols\n", VTableSymCount);
	}

	// ============ Section 3: Function Symbols ============
	Lua << "-- ============ Function Symbols ============\n";
	{
		int32 FuncSymCount = 0;

		for (UEObject Obj : ObjectArray())
		{
			if (!Obj.IsA(EClassCastFlags::Function))
				continue;

			UEFunction Func = Obj.Cast<UEFunction>();
			void* ExecFunc = Func.GetExecFunction();
			if (!ExecFunc)
				continue;
			uintptr_t ExecOffset = Platform::GetOffset(ExecFunc);

			if (ExecOffset == 0)
				continue;

			// Get owning class name
			UEObject Outer = Func.GetOuter();
			if (!Outer)
				continue;

			std::string ClassName = Outer.GetCppName();
			std::string FuncName = Func.GetValidName();

			// CE symbol names can't have certain characters
			Lua << std::format("reg(\"{}::{}\", base + 0x{:X})\n", ClassName, FuncName, ExecOffset);
			FuncSymCount++;
		}

		Lua << "\n";
		std::cerr << std::format("CE Symbols: {} function symbols\n", FuncSymCount);
	}

	// ============ Section 4: Structure Definitions ============
	Lua << "-- ============ Structure Definitions ============\n";
	Lua << "-- CE createStructure() definitions for memory dissection\n\n";
	{
		int32 StructCount = 0;

		for (PackageInfoHandle Package : PackageManager::IterateOverPackageInfos())
		{
			if (Package.IsEmpty())
				continue;

			auto WriteStructDef = [&](int32 Index) -> void
			{
				StructWrapper Struct(ObjectArray::GetByIndex<UEStruct>(Index));
				if (!Struct.IsValid())
					return;

				std::string StructName = GetStructPrefixedName(Struct);
				int32 StructSize = Struct.GetSize();

				if (StructSize <= 0)
					return;

				// Escape quotes in name for Lua string
				std::string SafeName = StructName;
				for (auto& c : SafeName) { if (c == '"') c = '_'; }

				Lua << std::format("do local s = createStructure(\"{}\"); s.Size = 0x{:X}; s.DoNotSave = true\n", SafeName, StructSize);

				MemberManager Members = Struct.GetMembers();
				for (const PropertyWrapper& Prop : Members.IterateMembers())
				{
					int32 Offset = Prop.GetOffset();
					int32 Size = Prop.GetSize();
					std::string MemberName = Prop.GetName();

					// Determine CE variable type
					const char* VarType = "vtByteArray";
					if (Size == 1) VarType = "vtByte";
					else if (Size == 2) VarType = "vtWord";
					else if (Size == 4) VarType = "vtDword";
					else if (Size == 8) VarType = "vtQword";

					// Check for float/double
					if (Prop.IsUnrealProperty())
					{
						auto [Class, FieldClass] = Prop.GetUnrealProperty().GetClass();
						EClassCastFlags Flags = Class ? Class.GetCastFlags() : FieldClass.GetCastFlags();

						if (Flags & EClassCastFlags::FloatProperty)
							VarType = "vtSingle";
						else if (Flags & EClassCastFlags::DoubleProperty)
							VarType = "vtDouble";
						else if (Flags & EClassCastFlags::ObjectProperty)
							VarType = "vtPointer";
						else if (Flags & EClassCastFlags::ClassProperty)
							VarType = "vtPointer";
					}

					// Escape member name
					std::string SafeMember = MemberName;
					for (auto& c : SafeMember) { if (c == '"') c = '_'; }

					Lua << std::format("  local e = s:addElement(); e.Offset = 0x{:X}; e.Name = \"{}\"; e.Vartype = {}; e.Bytesize = 0x{:X}\n",
						Offset, SafeMember, VarType, Size);
				}

				Lua << "end\n";
				StructCount++;
			};

			if (Package.HasStructs())
				Package.GetSortedStructs().VisitAllNodesWithCallback(WriteStructDef);

			if (Package.HasClasses())
				Package.GetSortedClasses().VisitAllNodesWithCallback(WriteStructDef);
		}

		Lua << "\n";
		std::cerr << std::format("CE Symbols: {} structure definitions\n", StructCount);
	}

	// ============ Section 5: Enum Definitions ============
	Lua << "-- ============ Enum Definitions ============\n";
	Lua << "-- Stored as Lua tables for reference\n";
	Lua << "Dumper7_Enums = {}\n\n";
	{
		int32 EnumCount = 0;

		for (PackageInfoHandle Package : PackageManager::IterateOverPackageInfos())
		{
			if (Package.IsEmpty())
				continue;

			for (int32 EnumIdx : Package.GetEnums())
			{
				EnumWrapper Enum(ObjectArray::GetByIndex<UEEnum>(EnumIdx));
				if (!Enum.IsValid())
					continue;

				std::string EnumName = GetEnumPrefixedName(Enum);
				std::string SafeName = EnumName;
				for (auto& c : SafeName) { if (c == '"' || c == ':') c = '_'; }

				Lua << std::format("Dumper7_Enums[\"{}\"] = {{\n", SafeName);

				for (const EnumCollisionInfo& Info : Enum.GetMembers())
				{
					std::string ValName = Info.GetUniqueName();
					for (auto& c : ValName) { if (c == '"') c = '_'; }
					Lua << std::format("  [\"{}\"] = {},\n", ValName, Info.GetValue());
				}

				Lua << "}\n";
				EnumCount++;
			}
		}

		Lua << "\n";
		std::cerr << std::format("CE Symbols: {} enum definitions\n", EnumCount);
	}

	Lua << "print(string.format(\"Dumper-7: %d symbols registered.\", symCount))\n";
	Lua.close();
	std::cerr << "ce_symbols.lua generated.\n\n";
}

void DumpspaceGenerator::Generate()
{
	/* Set the output directory of DSGen to "...GenerationPath/GameVersion-GameName/Dumespace" */
	DSGen::setDirectory(MainFolder);

	/* Add offsets for GObjects, GNames, GWorld, AppendString, PrcessEvent and ProcessEventIndex*/
	GeneratedStaticOffsets();

	// Generates all packages and writes them to files
	for (PackageInfoHandle Package : PackageManager::IterateOverPackageInfos())
	{
		if (Package.IsEmpty())
			continue;

		/*
		* Generate classes/structs/enums/functions directly into the respective files
		*
		* Note: Some filestreams aren't opened but passed as parameters anyway because the function demands it, they are not used if they are closed
		*/
		for (int32 EnumIdx : Package.GetEnums())
		{
			DSGen::EnumHolder Enum = GenerateEnum(ObjectArray::GetByIndex<UEEnum>(EnumIdx));
			DSGen::bakeEnum(Enum);
		}

		DependencyManager::OnVisitCallbackType GenerateClassOrStructCallback = [&](int32 Index) -> void
		{
			DSGen::ClassHolder StructOrClass = GenerateStruct(ObjectArray::GetByIndex<UEStruct>(Index));
			DSGen::bakeStructOrClass(StructOrClass);
		};

		if (Package.HasStructs())
		{
			const DependencyManager& Structs = Package.GetSortedStructs();

			Structs.VisitAllNodesWithCallback(GenerateClassOrStructCallback);
		}

		if (Package.HasClasses())
		{
			const DependencyManager& Classes = Package.GetSortedClasses();

			Classes.VisitAllNodesWithCallback(GenerateClassOrStructCallback);
		}
	}

	DSGen::dump();

	// Write the IDAPython importer script in binary mode to preserve LF line endings
	{
		std::ofstream ScriptFile(MainFolder / "dumper7_ida_import.py", std::ios::binary);
		ScriptFile.write(EMBEDDED_IDA_DUMPSPACE_SCRIPT, sizeof(EMBEDDED_IDA_DUMPSPACE_SCRIPT) - 1);
	}

	// Dump vtable RVAs for key UE classes
	GenerateVTableInfo(MainFolder);

	// Generate comprehensive CE symbol script
	GenerateCESymbols(MainFolder);

	// Export all DataTable row data as JSON
	GenerateDataTables(Generator::GetDumperFolder());
}


/* ── DataTable Dumper helpers ── */

static std::string EscapeJsonString(const std::string& Input)
{
	std::string Out;
	Out.reserve(Input.size() + 8);
	for (char c : Input)
	{
		switch (c)
		{
		case '"':  Out += "\\\""; break;
		case '\\': Out += "\\\\"; break;
		case '\n': Out += "\\n";  break;
		case '\r': Out += "\\r";  break;
		case '\t': Out += "\\t";  break;
		default:   Out += c;      break;
		}
	}
	return Out;
}

static void WritePropertyValueAsJson(std::ofstream& Out, UEProperty Prop, const uint8* RowData, int Depth = 0);

static void WriteStructPropertiesAsJson(std::ofstream& Out, UEStruct Struct, const uint8* Data, int Depth)
{
	auto Props = Struct.GetProperties();
	Out << "{";
	bool bFirst = true;
	for (auto& P : Props)
	{
		if (!bFirst) Out << ",";
		bFirst = false;
		Out << "\n" << std::string((Depth + 1) * 2, ' ');
		Out << "\"" << EscapeJsonString(P.GetValidName()) << "\": ";
		WritePropertyValueAsJson(Out, P, Data, Depth + 1);
	}
	if (!Props.empty())
		Out << "\n" << std::string(Depth * 2, ' ');
	Out << "}";
}

static void WritePropertyValueAsJson(std::ofstream& Out, UEProperty Prop, const uint8* RowData, int Depth)
{
	const int32 Offset = Prop.GetOffset();
	const int32 Size = Prop.GetSize();
	const uint8* Data = RowData + Offset;

	EClassCastFlags TypeFlags = EClassCastFlags::None;
	{
		auto [UClass, FFieldClass] = Prop.GetClass();
		TypeFlags = UClass ? UClass.GetCastFlags() : FFieldClass.GetCastFlags();
	}

	try
	{
		if (TypeFlags & EClassCastFlags::BoolProperty)
		{
			auto BoolProp = Prop.Cast<UEBoolProperty>();
			uint8 FieldMask = BoolProp.GetFieldMask();
			uint8 ByteOffset = BoolProp.GetByteOffset();
			bool bValue = (*(RowData + Offset + ByteOffset) & FieldMask) != 0;
			Out << (bValue ? "true" : "false");
		}
		else if (TypeFlags & EClassCastFlags::Int8Property)
		{
			Out << static_cast<int>(*reinterpret_cast<const int8*>(Data));
		}
		else if (TypeFlags & EClassCastFlags::ByteProperty)
		{
			Out << static_cast<int>(*Data);
		}
		else if (TypeFlags & EClassCastFlags::Int16Property)
		{
			Out << *reinterpret_cast<const int16*>(Data);
		}
		else if (TypeFlags & EClassCastFlags::UInt16Property)
		{
			Out << *reinterpret_cast<const uint16*>(Data);
		}
		else if (TypeFlags & EClassCastFlags::IntProperty)
		{
			Out << *reinterpret_cast<const int32*>(Data);
		}
		else if (TypeFlags & EClassCastFlags::UInt32Property)
		{
			Out << *reinterpret_cast<const uint32*>(Data);
		}
		else if (TypeFlags & EClassCastFlags::Int64Property)
		{
			Out << *reinterpret_cast<const int64*>(Data);
		}
		else if (TypeFlags & EClassCastFlags::UInt64Property)
		{
			Out << *reinterpret_cast<const uint64*>(Data);
		}
		else if (TypeFlags & EClassCastFlags::FloatProperty)
		{
			float v = *reinterpret_cast<const float*>(Data);
			if (std::isnan(v) || std::isinf(v)) Out << "null";
			else Out << v;
		}
		else if (TypeFlags & EClassCastFlags::DoubleProperty)
		{
			double v = *reinterpret_cast<const double*>(Data);
			if (std::isnan(v) || std::isinf(v)) Out << "null";
			else Out << v;
		}
		else if (TypeFlags & EClassCastFlags::NameProperty)
		{
			FName Name(Data);
			Out << "\"" << EscapeJsonString(Name.ToString()) << "\"";
		}
		else if (TypeFlags & EClassCastFlags::StrProperty)
		{
			const auto* Str = reinterpret_cast<const FString*>(Data);
			if (Str->IsValid() && Str->Num() > 0)
			{
				std::wstring Wide(Str->CStr(), Str->Num() - 1);
				std::string Narrow(Wide.begin(), Wide.end());
				Out << "\"" << EscapeJsonString(Narrow) << "\"";
			}
			else
			{
				Out << "\"\"";
			}
		}
		else if (TypeFlags & EClassCastFlags::EnumProperty)
		{
			auto EnumProp = Prop.Cast<UEEnumProperty>();
			UEProperty UnderlyingProp = EnumProp.GetUnderlayingProperty();
			int64 Val = 0;
			if (UnderlyingProp)
			{
				int32 USize = UnderlyingProp.GetSize();
				if (USize == 1) Val = *reinterpret_cast<const uint8*>(Data);
				else if (USize == 2) Val = *reinterpret_cast<const uint16*>(Data);
				else if (USize == 4) Val = *reinterpret_cast<const int32*>(Data);
				else if (USize == 8) Val = *reinterpret_cast<const int64*>(Data);
			}
			else
			{
				Val = *reinterpret_cast<const uint8*>(Data);
			}
			Out << Val;
		}
		else if (TypeFlags & EClassCastFlags::ObjectProperty)
		{
			void* ObjPtr = *reinterpret_cast<void* const*>(Data);
			if (ObjPtr)
			{
				UEObject Obj(ObjPtr);
				Out << "\"" << EscapeJsonString(Obj.GetName()) << "\"";
			}
			else
			{
				Out << "null";
			}
		}
		else if (TypeFlags & EClassCastFlags::StructProperty)
		{
			auto StructProp = Prop.Cast<UEStructProperty>();
			UEStruct InnerStruct = StructProp.GetUnderlayingStruct();
			if (InnerStruct && Depth < 3)
			{
				WriteStructPropertiesAsJson(Out, InnerStruct, Data, Depth);
			}
			else
			{
				Out << "\"<struct>\"";
			}
		}
		else if (TypeFlags & EClassCastFlags::ArrayProperty)
		{
			const auto* Arr = reinterpret_cast<const TArray<uint8>*>(Data);
			if (Arr && Arr->IsValid())
				Out << "\"<array[" << Arr->Num() << "]>\"";
			else
				Out << "\"<array>\"";
		}
		else if (TypeFlags & EClassCastFlags::TextProperty)
		{
			Out << "\"<FText>\"";
		}
		else if (TypeFlags & EClassCastFlags::MapProperty)
		{
			Out << "\"<TMap>\"";
		}
		else
		{
			/* Fallback: hex dump for unknown types */
			if (Size <= 8)
			{
				uint64 Raw = 0;
				memcpy(&Raw, Data, Size);
				Out << std::format("\"0x{:X}\"", Raw);
			}
			else
			{
				Out << "\"<" << Size << " bytes>\"";
			}
		}
	}
	catch (...)
	{
		Out << "\"<error>\"";
	}
}

void DumpspaceGenerator::GenerateDataTables(const fs::path& DumperFolder)
{
	const UEClass DataTableClass = ObjectArray::FindClassFast("DataTable");
	if (!DataTableClass)
	{
		std::cerr << "DataTable class not found, skipping DataTable export.\n";
		return;
	}

	const int32 RowMapOffset = Off::InSDK::UDataTable::RowMap;
	const int32 RowStructOffset = RowMapOffset - static_cast<int32>(sizeof(void*));
	const int32 FNameSz = Off::InSDK::Name::FNameSize;

	struct alignas(0x4) Name08 { uint8 Pad[0x08]; };
	struct alignas(0x4) Name16 { uint8 Pad[0x10]; };

	const fs::path DataTablesDir = DumperFolder / "DataTables";
	std::error_code ec;
	fs::create_directories(DataTablesDir, ec);

	int TableCount = 0;

	for (UEObject Obj : ObjectArray())
	{
		if (!Obj.IsA(DataTableClass))
			continue;

		try
		{
			uint8* ObjPtr = reinterpret_cast<uint8*>(const_cast<void*>(Obj.GetAddress()));
			if (!ObjPtr) continue;

			/* Read RowStruct pointer (UScriptStruct*) */
			UEStruct RowStruct(*reinterpret_cast<void**>(ObjPtr + RowStructOffset));
			if (!RowStruct) continue;

			std::string TableName = Obj.GetName();
			std::string RowStructName = RowStruct.GetName();
			auto RowProps = RowStruct.GetProperties();

			/* Build output path: DataTables/<TableName>.json */
			std::string SafeTableName = TableName;
			FileNameHelper::MakeValidFileName(SafeTableName);
			fs::path OutPath = DataTablesDir / (SafeTableName + ".json");

			std::ofstream File(OutPath);
			if (!File.is_open()) continue;

			/* JSON header */
			File << "{\n";
			File << "  \"table_name\": \"" << EscapeJsonString(TableName) << "\",\n";
			File << "  \"row_struct\": \"" << EscapeJsonString(RowStructName) << "\",\n";

			/* Column definitions */
			File << "  \"columns\": [";
			for (size_t i = 0; i < RowProps.size(); i++)
			{
				if (i > 0) File << ",";
				File << "\n    {\"name\": \"" << EscapeJsonString(RowProps[i].GetValidName())
					 << "\", \"type\": \"" << EscapeJsonString(RowProps[i].GetCppType())
					 << "\", \"offset\": \"0x" << std::format("{:X}", RowProps[i].GetOffset())
					 << "\", \"size\": " << RowProps[i].GetSize() << "}";
			}
			if (!RowProps.empty()) File << "\n  ";
			File << "],\n";

			/* Iterate RowMap: TMap<FName, uint8*> */
			File << "  \"rows\": {";
			int RowCount = 0;
			bool bFirstRow = true;

			auto ProcessRowMap = [&]<typename NameType>(TMap<NameType, uint8*>& Map)
			{
				for (auto It = begin(Map); It != end(Map); ++It)
				{
					const uint8* RowData = It->Value();
					if (!RowData) continue;

					FName RowName(&It->Key());
					std::string RowNameStr = RowName.ToString();

					if (!bFirstRow) File << ",";
					bFirstRow = false;
					File << "\n    \"" << EscapeJsonString(RowNameStr) << "\": ";

					WriteStructPropertiesAsJson(File, RowStruct, RowData, 2);
					RowCount++;
				}
			};

			if (FNameSz > 0x8)
				ProcessRowMap(*reinterpret_cast<TMap<Name16, uint8*>*>(ObjPtr + RowMapOffset));
			else
				ProcessRowMap(*reinterpret_cast<TMap<Name08, uint8*>*>(ObjPtr + RowMapOffset));

			File << "\n  },\n";
			File << "  \"row_count\": " << RowCount << "\n";
			File << "}\n";

			TableCount++;
		}
		catch (const std::exception& e)
		{
			std::cerr << "DataTable export error: " << e.what() << "\n";
		}
		catch (...)
		{
			std::cerr << "DataTable export: unknown error\n";
		}
	}

	std::cerr << std::format("DataTable export: {} tables written to DataTables/\n", TableCount);
}
