"""
The HyperV module allows for the management of HyperV capable windows machines.
"""
import json

from eikobot.core.handlers import CRUDHandler, HandlerContext
from eikobot.core.helpers import EikoBaseModel
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
    host: HyperVHostModel


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

        get_switch_res = await ctx.resource.host.execute(
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

        await ctx.resource.host.execute(
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

        await ctx.resource.host.execute(
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

    async def read(self, ctx: HandlerContext) -> None:
        if not isinstance(ctx.resource, ExternalSwitchModel):
            ctx.failed = True
            return

        super().read(ctx)
        info: dict[str, str] = ctx["info"]
        if info.get("IovEnabled") != ctx.resource.enable_Iov:
            ctx.add_change("IovEnabled", ctx.resource.enable_Iov)

        if info.get("AllowManagementOS") != ctx.resource.allow_management_OS:
            ctx.add_change("AllowManagementOS", ctx.resource.allow_management_OS)

        net_adapter_name = (
            await ctx.resource.host.execute(
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

        await ctx.resource.host.execute(cmd_str, ctx)
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

        await ctx.resource.host.execute(cmd_str, ctx)
        ctx.deployed = True
