"""
The HyperV module allows for the management of HyperV capable windows machines.
"""
import json
from pathlib import Path

from eikobot.core.handlers import CRUDHandler, HandlerContext
from eikobot.core.helpers import EikoBaseModel, machine_readable
from eikobot.core.lib.std import HostHandler, HostModel


class HyperVHostModel(HostModel):
    """
    Represents a Host that has Hyper-V installed.
    """

    __eiko_resource__ = "HyperVHost"

    install: bool = False


class HyperVHostHandler(HostHandler):
    """
    Represents a remote host.
    """

    __eiko_resource__ = "HyperVHost"

    async def execute(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, HyperVHostModel):
            ctx.failed = True
            return

        await super().execute(ctx)
        ctx.deployed = False

        if not ctx.resource.is_windows_host:
            ctx.error("Host doesn't seem to be a Windows machine.")
            ctx.failed = True
            return

        os_string = ctx.resource.os_version.resolve(str)
        if "10" in os_string:
            result = await ctx.resource.execute(
                "Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V | ConvertTo-Json",
                ctx,
            )
            output_dict: dict = json.loads(result.output)
            if output_dict.get("State") == 2:
                ctx.debug("Hyper-V state: installed.")
                ctx.deployed = True
                return

        if ctx.resource.install:
            pass
        else:
            ctx.failed = True
            ctx.error(
                "Hyper-V is not installed on target and not set to install. "
                "Please manually install Hyper-V or set the install parameter to 'True'."
            )
            return


class VMSwitchModel(EikoBaseModel):
    """
    Represents a Host that has Hyper-V installed.
    Has no associated deploy tasks, purely virtual.
    Use InternalSwitch, PrivateSwitch or ExternalSwitch instead.
    """

    __eiko_resource__ = "VMSwitch"

    name: str
    vm_host: HyperVHostModel


class VMSwitchHandler(CRUDHandler):
    """
    Because reading a switch is the same, independant of type,
    this handler is a good basis for the others to inherit from.
    """

    __eiko_resource__ = "VMSwitch"

    async def read(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, VMSwitchModel):
            ctx.failed = True
            return

        get_switch_res = await ctx.resource.vm_host.execute(
            f'Get-VMSwitch -Name "{ctx.resource.name}" | convertto-json',
            ctx,
        )

        if "Hyper-V was unable to find a virtual switch" in get_switch_res.output:
            return

        ctx.deployed = True
        ctx.extras["info"] = json.loads(get_switch_res.output)


class InternalSwitchModel(VMSwitchModel):
    """
    A Hyper-V virtual switch that connects VMs with the host and other VMs.
    """

    __eiko_resource__ = "InternalSwitch"


class InternalSwitchHandler(VMSwitchHandler):
    """
    A Hyper-V virtual switch that connects VMs with the host and other VMs.
    """

    __eiko_resource__ = "InternalSwitch"

    async def create(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, InternalSwitchModel):
            ctx.failed = True
            return

        await ctx.resource.vm_host.execute(
            f'New-VMSwitch -name "{ctx.resource.name}" -SwitchType Internal',
            ctx,
        )
        ctx.deployed = True


class PrivateSwitchModel(VMSwitchModel):
    """
    A Hyper-V virtual switch that connects VMs with other VMs.
    """

    __eiko_resource__ = "PrivateSwitch"


class PrivateSwitchHandler(VMSwitchHandler):
    """
    A Hyper-V virtual switch that connects VMs with other VMs.
    """

    __eiko_resource__ = "PrivateSwitch"

    async def create(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, PrivateSwitchModel):
            ctx.failed = True
            return

        await ctx.resource.vm_host.execute(
            f'New-VMSwitch -name "{ctx.resource.name}" -SwitchType Private',
            ctx,
        )
        ctx.deployed = True


class ExternalSwitchModel(VMSwitchModel):
    """
    A Hyper-V virtual switch that connects VMs with a network adapter,
    so they can reach the outside world.
    This optionally bars the Host OS from using the switch.
    """

    __eiko_resource__ = "ExternalSwitch"

    net_adapter_name: str
    allow_management_OS: bool | None = None
    enable_Iov: bool | None = None


class ExternalSwitchHandler(VMSwitchHandler):
    """
    A Hyper-V virtual switch that connects VMs with a network adapter,
    so they can reach the outside world.
    This optionally bars the Host OS from using the switch.
    """

    __eiko_resource__ = "ExternalSwitch"

    async def read(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, ExternalSwitchModel):
            ctx.failed = True
            return

        await super().read(ctx)
        info: dict[str, str] = ctx["info"]  # type: ignore
        if info.get("IovEnabled") != ctx.resource.enable_Iov:
            ctx.add_change("IovEnabled", ctx.resource.enable_Iov)

        if info.get("AllowManagementOS") != ctx.resource.allow_management_OS:
            ctx.add_change("AllowManagementOS", ctx.resource.allow_management_OS)

        net_adapter_name = (
            await ctx.resource.vm_host.execute(
                f'(Get-NetAdapter -InterfaceDescription (Get-VMSwitch "{ctx.resource.name}"'
                ").NetAdapterInterfaceDescription).name",
                ctx,
            )
        ).output

        if net_adapter_name != ctx.resource.name:
            ctx.add_change("NetAdapterName", ctx.resource.name)

    async def create(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, ExternalSwitchModel):
            ctx.failed = True
            return

        cmd_str = f'New-VMSwitch -name "{ctx.resource.name}" '
        cmd_str += "-SwitchType External "
        cmd_str += f'-NetAdapterName "{ctx.resource.net_adapter_name}" '

        if ctx.resource.allow_management_OS is not None:
            cmd_str += f"-AllowManagementOS:${ctx.resource.allow_management_OS} "

        if ctx.resource.enable_Iov is not None:
            cmd_str += f"-EnableIov:${ctx.resource.enable_Iov}"

        await ctx.resource.vm_host.execute(cmd_str, ctx)
        ctx.deployed = True

    async def update(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, ExternalSwitchModel):
            ctx.failed = True
            return

        cmd_str = f'Set-VMSwitch -name "{ctx.resource.name}" '

        net_adapter_name = ctx.changes.get("NetAdapterName")
        if net_adapter_name is not None:
            cmd_str += f'-NetAdapterName "{net_adapter_name}" '

        enable_iov = ctx.changes.get("IovEnabled")
        if enable_iov is not None:
            cmd_str += f"-EnableIov:${ctx.resource.enable_Iov} "

        allow_management_os = ctx.changes.get("AllowManagementOS")
        if allow_management_os is not None:
            cmd_str += f"-AllowManagementOS:${ctx.resource.allow_management_OS} "

        await ctx.resource.vm_host.execute(cmd_str, ctx)
        ctx.deployed = True


class VHDModel(EikoBaseModel):
    """
    Represents a VHD to deploy on a Hyper-V Host
    """

    __eiko_resource__ = "VHD"

    path: Path
    vm_host: HyperVHostModel
    size: str
    vhd_type: str


class VHDHandler(CRUDHandler):
    """
    Deploy a VHD on a Hyper-V Host
    """

    __eiko_resource__ = "VHD"

    async def create(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, VHDModel):
            ctx.failed = True
            return

        await ctx.resource.vm_host.execute(
            f'New-VHD -Path "{ctx.resource.path}" -{ctx.resource.vhd_type} -SizeBytes {ctx.resource.size}',
            ctx,
        )

        ctx.deployed = True

    async def read(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, VHDModel):
            ctx.failed = True
            return

        result = await ctx.resource.vm_host.execute(
            f'Get-VHD "{ctx.resource.path}" | ConvertTo-Json',
            ctx,
        )

        if "is not an existing virtual hard disk file." not in result.output:
            ctx.deployed = True


class VMModel(EikoBaseModel):
    """
    Represents a VM to deploy on a Hyper-V host
    """

    __eiko_resource__ = "VM"

    name: str
    vm_host: HyperVHostModel

    path: Path | None = None
    cpu_count: int = 1
    boot_device: str | None = None
    vhds: list[VHDModel] = []
    switches: list[VMSwitchModel] = []
    iso_path: Path | None = None

    startup_ram: str = "1024MB"
    dynamic_ram: bool = False
    min_ram: str = "512MB"
    max_ram: str = "2048MB"

    automatic_start_action: str | None = None
    automatic_stop_action: str | None = None
    automatic_start_delay: int | None = None

    secure_boot: bool | None = None
    secure_boot_template: str | None = None


class VMHandler(CRUDHandler):
    """
    Deploys a VM on a Hyper-V host.
    """

    __eiko_resource__ = "VM"

    async def create(self, ctx: HandlerContext[VMModel]) -> None:
        vm = ctx.resource
        script = "\n"
        new_vm_cmd = f"New-VM -Name {vm.name} -NoVHD -Generation 2 "
        new_vm_cmd += f"-MemoryStartupBytes {vm.startup_ram} "
        if vm.path is not None:
            script += f'New-Item -Path "{vm.path}/VM" -ItemType Directory -force\n'
            new_vm_cmd += f'-Path "{vm.path}/VM"'

        set_vmdrive = ""
        if vm.iso_path is not None:
            new_vm_cmd += '-BootDevice "CD"'
            set_vmdrive += f"Set-VMDvdDrive -VMName {vm.name} "
            set_vmdrive += f"-Path {vm.iso_path}\n"
        script += new_vm_cmd + "\n"

        script += f"Set-VM -Name {vm.name} -ProcessorCount {vm.cpu_count} "
        script += f'-Notes "Eikobot created VM {ctx.task_id}"\n'

        ram_cmd = f"Set-VMMemory -VMName {vm.name} "
        ram_cmd += "-DynamicMemoryEnabled "
        if vm.dynamic_ram:
            ram_cmd += "$true "
            ram_cmd += f"-MinimumBytes {vm.min_ram} "
            ram_cmd += f"-MaximumBytes {vm.max_ram}"
        else:
            ram_cmd += "$false "
        script += ram_cmd + "\n"

        if vm.secure_boot is not None:
            set_vmfirmware = f"Set-VMFirmware -VMName {vm.name} "
            if vm.secure_boot:
                set_vmfirmware += "-EnableSecureBoot On "
            else:
                set_vmfirmware += "-EnableSecureBoot Off "

            if vm.secure_boot_template is not None:
                set_vmfirmware += (
                    "-SecureBootTemplate MicrosoftUEFICertificateAuthority"
                )
            script += set_vmfirmware + "\n"

        script += set_vmdrive

        for vhd in vm.vhds:
            add_vhd = f'Add-VMHardDiskDrive -VMName "{vm.name}" '
            add_vhd += f' -Path "{vhd.path}"\n'
            script += add_vhd

        rm_net_adapter = f'Remove-VMNetworkAdapter -VMName "{vm.name}" '
        rm_net_adapter += '-Name "Network Adapter"\n'
        script += rm_net_adapter

        for switch in vm.switches:
            new_adapter = f'Add-VMNetworkAdapter -VMName "{vm.name}" '
            new_adapter += f'-Name "{switch.name} Network Adapter"\n'
            script += new_adapter
            attach_switch = f'Connect-VMNetworkAdapter -VMName "{vm.name}" '
            attach_switch += f'-Name "{switch.name} Network Adapter" '
            attach_switch += f'-SwitchName "{switch.name}"\n'
            script += attach_switch

        await vm.vm_host.script(script, "powershell", ctx)
        ctx.deployed = True

    async def read(self, ctx: HandlerContext[VMModel]) -> None:
        vm = ctx.resource
        results = await vm.vm_host.execute(
            f'Get-VM "{vm.name}" | ConvertTo-Json',
            ctx,
        )
        if "Hyper-V was unable to find a virtual machine" in results.output:
            return

        vm_dict: dict = json.loads(results.output)

        path = Path(vm_dict.get("ConfigurationLocation"))  # type: ignore
        if vm.path is not None and path != (vm.path / f"VM/{ctx.resource.name}"):
            ctx.changes["path"] = path
            ctx.warning(
                "Path of VM config files was changed in model, "
                "but this change is currently not supported and will be ignored."
            )

        await self._get_cpu_changes(vm, ctx)

        if vm.boot_device is not None:
            ctx.debug("Changes to boot order are ignored.")

        self._compare_vhds(vm, vm_dict.get("HardDrives", []), ctx)
        added_adapters = self._compare_net_adapters(
            vm, vm_dict.get("NetworkAdapters", []), ctx
        )
        if added_adapters:
            ctx.debug("Some network adapters are missing from VM.")
            ctx.add_change("net_adapters", added_adapters)

        self._compare_ram(vm, vm_dict, ctx)
        await self._compare_startup_options(vm, ctx)
        await self._compare_secure_boot(vm, ctx)

        ctx.deployed = True

    async def _get_cpu_changes(self, vm: VMModel, ctx: HandlerContext) -> None:
        results = await vm.vm_host.execute(
            f'Get-VMProcessor "{vm.name}" | ConvertTo-Json',
            ctx,
        )
        cpu_dict: dict = json.loads(results.output)

        cpu_count = int(cpu_dict.get("Count", 1))
        if cpu_count != vm.cpu_count:
            ctx.changes["cpu_count"] = cpu_count

    def _compare_vhds(self, vm: VMModel, vhds: list[dict], ctx: HandlerContext) -> None:
        vhd_cmds = ""
        for vhd in vm.vhds:
            for vhd_dict in vhds:
                if vhd.path == Path(vhd_dict["Path"]):
                    ctx.debug(f"VHD match: '{vhd.path}'.")
                    break
            else:
                ctx.debug("Hard drives are missing from VM.")
                add_vhd = f'Add-VMHardDiskDrive -VMName "{vm.name}" '
                add_vhd += f' -Path "{vhd.path}"\n'
                vhd_cmds += add_vhd

        if vhd_cmds != "":
            ctx.add_change("VHDs", vhd_cmds)

    def _compare_net_adapters(
        self, vm: VMModel, net_adapters: list[dict], ctx: HandlerContext
    ) -> list[VMSwitchModel]:
        added_adapters: list[VMSwitchModel] = []
        for switch in vm.switches:
            for net_adapter in net_adapters:
                if switch.name == net_adapter.get("SwitchName"):
                    ctx.debug(f"Switch is already attached: '{switch.name}'.")
                    break
            else:
                added_adapters.append(switch)

        return added_adapters

    def _compare_ram(self, vm: VMModel, vm_dict: dict, ctx: HandlerContext) -> None:
        startup_ram = vm_dict.get("MemoryStartup")
        if startup_ram != machine_readable(vm.startup_ram):
            ctx.add_change("startup_ram", vm.startup_ram)

        dynamic_ram = vm_dict.get("DynamicMemoryEnabled")
        if dynamic_ram != vm.dynamic_ram:
            ctx.add_change("dynamic_ram", vm.dynamic_ram)

        if vm.dynamic_ram:
            min_ram = vm_dict.get("MemoryMinimum")
            if min_ram != machine_readable(vm.min_ram):
                ctx.add_change("min_ram", vm.min_ram)

            max_ram = vm_dict.get("MemoryMaximum")
            if max_ram != machine_readable(vm.max_ram):
                ctx.add_change("max_ram", vm.max_ram)

    async def _compare_startup_options(self, vm: VMModel, ctx: HandlerContext) -> None:
        if vm.automatic_start_action is not None:
            automatic_start_action = (
                await vm.vm_host.execute(
                    f'(Get-VM "{vm.name}").AutomaticStartAction',
                    ctx,
                )
            ).output
            if automatic_start_action != vm.automatic_start_action:
                ctx.add_change("automatic_start_action", vm.automatic_start_action)

        if vm.automatic_start_delay is not None:
            automatic_start_delay = (
                await vm.vm_host.execute(
                    f'(Get-VM "{vm.name}").AutomaticStartDelay',
                    ctx,
                )
            ).output
            if automatic_start_delay != vm.automatic_start_delay:
                ctx.add_change("automatic_start_delay", vm.automatic_start_delay)

        if vm.automatic_stop_action is not None:
            automatic_stop_action = (
                await vm.vm_host.execute(
                    f'(Get-VM "{vm.name}").AutomaticStopAction',
                    ctx,
                )
            ).output
            if automatic_stop_action != vm.automatic_stop_action:
                ctx.add_change("automatic_stop_action", vm.automatic_stop_action)

    async def _compare_secure_boot(
        self, vm: VMModel, ctx: HandlerContext[VMModel]
    ) -> None:
        if vm.secure_boot is not None:
            secure_boot = (
                await vm.vm_host.execute(
                    f'(Get-VM "{vm.name}").SecureBoot',
                    ctx,
                )
            ).output
            if (secure_boot == "On") == vm.secure_boot:
                ctx.add_change("secure_boot", vm.secure_boot)

            if vm.secure_boot_template is not None:
                secure_boot_template = (
                    await vm.vm_host.execute(
                        f'(Get-VM "{vm.name}").SecureBoot',
                        ctx,
                    )
                ).output
                if secure_boot_template == vm.secure_boot_template:
                    ctx.add_change("secure_boot_template", vm.secure_boot_template)
