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
    description='Retrieval-augmented fault diagnosis for A.T.I.D.E. — watches fault state, '
                'reasons about recovery with Tavily + Nemotron via Nebius Token Factory. '
                'First iteration subscribes and logs only.',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'diagnostics_agent_node = atide_diagnostics_agent.diagnostics_agent_node:main',
        ],
    },
)