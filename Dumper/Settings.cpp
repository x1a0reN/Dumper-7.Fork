#include "Settings.h"

#include <Windows.h>
#include <filesystem>
#include <fstream>
#include <string>

#include "Unreal/UnrealObjects.h"
#include "Unreal/ObjectArray.h"

void Settings::InitWeakObjectPtrSettings()
{
	const UEStruct LoadAsset = ObjectArray::FindObjectFast<UEFunction>("LoadAsset", EClassCastFlags::Function);

	if (!LoadAsset)
	{
		std::cerr << "\nDumper-7: 'LoadAsset' wasn't found, could not determine value for 'bIsWeakObjectPtrWithoutTag'!\n" << std::endl;
		return;
	}

	const UEProperty Asset = LoadAsset.FindMember("Asset", EClassCastFlags::SoftObjectProperty);
	if (!Asset)
	{
		std::cerr << "\nDumper-7: 'Asset' wasn't found, could not determine value for 'bIsWeakObjectPtrWithoutTag'!\n" << std::endl;
		return;
	}

	const UEStruct SoftObjectPath = ObjectArray::FindStructFast("SoftObjectPath");

	constexpr int32 SizeOfFFWeakObjectPtr = 0x08;
	constexpr int32 OldUnrealAssetPtrSize = 0x10;
	const int32 SizeOfSoftObjectPath = SoftObjectPath ? SoftObjectPath.GetStructSize() : OldUnrealAssetPtrSize;

	Settings::Internal::bIsWeakObjectPtrWithoutTag = Asset.GetSize() <= (SizeOfSoftObjectPath + SizeOfFFWeakObjectPtr);

	//std::cerr << std::format("\nDumper-7: bIsWeakObjectPtrWithoutTag = {}\n", Settings::Internal::bIsWeakObjectPtrWithoutTag) << std::endl;
}

void Settings::InitLargeWorldCoordinateSettings()
{
	const UEStruct FVectorStruct = ObjectArray::FindStructFast("Vector");

	if (!FVectorStruct) [[unlikely]]
	{
		std::cerr << "\nSomething went horribly wrong, FVector wasn't even found!\n\n" << std::endl;
		return;
	}

	const UEProperty XProperty = FVectorStruct.FindMember("X");

	if (!XProperty) [[unlikely]]
	{
		std::cerr << "\nSomething went horribly wrong, FVector::X wasn't even found!\n\n" << std::endl;
		return;
	}

		/* Check the underlaying type of FVector::X. If it's double we're on UE5.0, or higher, and using large world coordinates. */
	Settings::Internal::bUseLargeWorldCoordinates = XProperty.IsA(EClassCastFlags::DoubleProperty);

	//std::cerr << std::format("\nDumper-7: bUseLargeWorldCoordinates = {}\n", Settings::Internal::bUseLargeWorldCoordinates) << std::endl;
}

void Settings::InitObjectPtrPropertySettings()
{
	const UEClass ObjectPtrPropertyClass = ObjectArray::FindClassFast("ObjectPtrProperty");

	if (!ObjectPtrPropertyClass)
	{
		// The class doesn't exist, this so FieldPathProperty couldn't have been replaced with ObjectPtrProperty
		std::cerr << std::format("\nDumper-7: bIsObjPtrInsteadOfFieldPathProperty = {}\n", Settings::Internal::bIsObjPtrInsteadOfFieldPathProperty) << std::endl;
		Settings::Internal::bIsObjPtrInsteadOfFieldPathProperty = false;
		return;
	}

	Settings::Internal::bIsObjPtrInsteadOfFieldPathProperty = ObjectPtrPropertyClass.GetDefaultObject().IsA(EClassCastFlags::FieldPathProperty);

	std::cerr << std::format("\nDumper-7: bIsObjPtrInsteadOfFieldPathProperty = {}\n", Settings::Internal::bIsObjPtrInsteadOfFieldPathProperty) << std::endl;
}

void Settings::InitArrayDimSizeSettings()
{
	/*
	 * UEProperty::GetArrayDim() is already fully functional at this point.
	 *
	 * This setting is just there to stop it from returning (int32)0xFFFFFF01 when it should be just (uint8)0x01.
	*/
	for (const UEObject Obj : ObjectArray())
	{
		if (!Obj.IsA(EClassCastFlags::Struct))
			continue;

		const UEStruct AsStruct = Obj.Cast<UEStruct>();

		for (const UEProperty Property : AsStruct.GetProperties())
		{
			// This number should just be 0x1 to indicate it's a single element, but the upper bytes aren't cleared to zero
			if (Property.GetArrayDim() >= 0x000F0001)
			{
				Settings::Internal::bUseUint8ArrayDim = true;
				std::cerr << std::format("\nDumper-7: bUseUint8ArrayDim = {}\n", Settings::Internal::bUseUint8ArrayDim) << std::endl;
				return;
			}
		}
	}

	Settings::Internal::bUseUint8ArrayDim = false;
	std::cerr << std::format("\nDumper-7: bUseUint8ArrayDim = {}\n", Settings::Internal::bUseUint8ArrayDim) << std::endl;
}

static void GenerateDefaultConfig(const std::string& Path)
{
	std::ofstream Out(Path);
	if (!Out.is_open())
		return;

	Out << "; Dumper-7 Configuration File (auto-generated defaults)\n";
	Out << "; Place this file next to Dumper-7.dll, in the game directory,\n";
	Out << "; or at C:/Dumper-7/Dumper-7.ini\n";
	Out << "\n";
	Out << "[Settings]\n";
	Out << "; Namespace name used in the generated SDK (default: SDK)\n";
	Out << "SDKNamespaceName=SDK\n";
	Out << "\n";
	Out << "; Delay in milliseconds before starting generation (default: 0)\n";
	Out << "SleepTimeout=0\n";
	Out << "\n";
	Out << "[PostRender]\n";
	Out << "; Manual override for vtable indices. Set to -1 for auto-detect.\n";
	Out << "GVCPostRenderIndex=-1\n";
	Out << "HUDPostRenderIndex=-1\n";
}

void Settings::Config::Load(void* hModule)
{
	namespace fs = std::filesystem;

	// Resolve DLL directory from module handle
	if (hModule)
	{
		char DllPath[MAX_PATH] = {};
		if (GetModuleFileNameA(static_cast<HMODULE>(hModule), DllPath, MAX_PATH) > 0)
		{
			DllDirectory = fs::path(DllPath).parent_path().string();
		}
	}

	// Search order: game dir → DLL dir → global path
	const std::string LocalPath = (fs::current_path() / "Dumper-7.ini").string();
	const std::string DllDirPath = DllDirectory.empty() ? std::string{} : (fs::path(DllDirectory) / "Dumper-7.ini").string();
	const char* ConfigPath = nullptr;

	if (fs::exists(LocalPath))
	{
		ConfigPath = LocalPath.c_str();
	}
	else if (!DllDirPath.empty() && fs::exists(DllDirPath))
	{
		ConfigPath = DllDirPath.c_str();
	}
	else if (fs::exists(GlobalConfigPath))
	{
		ConfigPath = GlobalConfigPath;
	}

	// No config found anywhere — generate default in DLL directory
	if (!ConfigPath)
	{
		const std::string DefaultPath = DllDirectory.empty()
			? (fs::current_path() / "Dumper-7.ini").string()
			: (fs::path(DllDirectory) / "Dumper-7.ini").string();

		GenerateDefaultConfig(DefaultPath);
		std::cerr << "Dumper-7: Generated default config at " << DefaultPath << "\n";
		return;
	}

	std::cerr << "Dumper-7: Loading config from " << ConfigPath << "\n";

	char SDKNamespace[256] = {};
	GetPrivateProfileStringA("Settings", "SDKNamespaceName", "SDK", SDKNamespace, sizeof(SDKNamespace), ConfigPath);

	SDKNamespaceName = SDKNamespace;
	SleepTimeout = max(GetPrivateProfileIntA("Settings", "SleepTimeout", 0, ConfigPath), 0);

	// [PostRender] section - manual override for vtable indices (-1 = auto-detect)
	int GVCIdx = GetPrivateProfileIntA("PostRender", "GVCPostRenderIndex", -1, ConfigPath);
	int HUDIdx = GetPrivateProfileIntA("PostRender", "HUDPostRenderIndex", -1, ConfigPath);

	if (GVCIdx >= 0)
		Settings::PostRender::GVCPostRenderIndex = GVCIdx;
	if (HUDIdx >= 0)
		Settings::PostRender::HUDPostRenderIndex = HUDIdx;
}
