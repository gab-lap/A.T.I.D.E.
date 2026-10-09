from setuptools import find_packages, setup

package_name = 'atide_diagnostics_agent'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Gabriele Lapini',
    maintainer_email='lelelapini1@gmail.com',
    description='Retrieval-augmented fault diagnosis for A.T.I.D.E. — watches fault '
                'state, retrieves ROS 2 recovery guidance via Tavily, reasons about the '
                'best action with NVIDIA Nemotron 3 Nano on Nebius Token Factory, and '
                'publishes the decision plus its full reasoning trace.',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'diagnostics_agent_node = atide_diagnostics_agent.diagnostics_agent_node:main',
            'baseline_agent_node = atide_diagnostics_agent.baseline_agent_node:main',
        ],
    },
)