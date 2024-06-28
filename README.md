# Eikobot Hyper-V module

A module for automating the installation of Hyper-V,
and management of Hyper-V VMs and Virtual Switches on windows hosts using eikobot.  

## Example

The following example creates VMs that are ready to have debian installed.  
It uses encapsulation to set sensible defaults and reduce required configuration.  

The only thing that is required is updating the path to your Debian ISO.  
When the VMs are started they simply launch from the ISO.  

First we set up some switches, as those will be the default switches used for
all our VMs.  
Next we create a resource class that encapsulates all the resources associated with a VM, such as the data paths, the VHD and the Hyper-V VM itself.  
Then we simply use said resource class to set up several VMs.  

```Python
import hyper_v


host = hyper_v.HyperVHost(
    "localhost",
)


internal_switch = hyper_v.InternalSwitch(
    "Internal",
    host,
)


default_switch = hyper_v.InternalSwitch(
    "Default Switch",
    host,
)


@index(["vm_host.host", "name"])
resource DebianVM:
    name: str
    vm_host: hyper_v.HyperVHost

    vm: hyper_v.VM

    def __init__(
        self,
        name: str,
        vm_host: hyper_v.HyperVHost,

        cpu_count: int = 2,
        ram: str = "2048MB",
    ):
        self.name = name
        self.vm_host = vm_host
        self.vm = hyper_v.VM(
            name,
            host,

            path=Path(f"c:/Hyper-V/Virtual Machines/{name}"),
            cpu_count=cpu_count,
            switches=[
                default_switch,
                internal_switch,
            ],
            vhds=[
                hyper_v.VHD(
                    Path(f"c:/Hyper-V/Virtual Machines/{name}/{name}.vhdx"),
                    self.vm_host,
                )
            ],

            iso_path=Path("C:/Hyper-V/Images/debian-12.0.0-amd64-netinst.iso"),
            secure_boot=True,
            secure_boot_template="MicrosoftUEFICertificateAuthority"
        )


DebianVM(
    "test-vm-1",
    host,
)


DebianVM(
    "test-vm-2",
    host,
    cpu_count=4,
    ram="4096MB"
)


DebianVM(
    "test-vm-3",
    host,
)
```
