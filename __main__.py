from ipykernel.kernelapp import IPKernelApp
from .kernel import TopazKernel
IPKernelApp.launch_instance(kernel_class=TopazKernel)
