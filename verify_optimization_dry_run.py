import sys
import unittest
from unittest.mock import MagicMock
import os

# 1. MOCK DOCKER
mock_docker = MagicMock()
sys.modules['docker'] = mock_docker
sys.modules['docker.errors'] = MagicMock()

# Mock dependencies
mock_client = MagicMock()
mock_docker.from_env.return_value = mock_client
mock_container = MagicMock()
mock_container.attrs = {
    'NetworkSettings': {'Ports': {}},
    'State': {'Running': True, 'Status': 'running'}
}
mock_client.containers.list.return_value = [] # No running containers implies ports are free
mock_client.containers.run.return_value = mock_container

# Add application to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import AFTER mocking
from application.services.docker_service_v2 import DockerService

class TestOptimizations(unittest.TestCase):
    def test_create_selenium_container_optimizations(self):
        service = DockerService()
        
        # Execute
        ports, container = service.create_selenium_container()
        
        # Verify
        mock_client.containers.run.assert_called_once()
        args, kwargs = mock_client.containers.run.call_args
        
        print("Container Run Args:", kwargs)
        
        # Check Memory Limit
        self.assertEqual(kwargs.get('mem_limit'), '1g', "Memory limit should be 1g")
        
        # Check Environment Variables for VNC
        env = kwargs.get('environment', {})
        self.assertEqual(env.get('SE_VNC_NO_PASSWORD'), '1', "VNC no password env var missing")
        self.assertEqual(env.get('SE_SCREEN_WIDTH'), '1920')
        
        # Check Image
        self.assertEqual(kwargs.get('image'), 'selenium/standalone-chrome:latest', "Should use official image")
        
        print("\n[SUCCESS] Verification Passed: DockerService is using optimized configuration.")

if __name__ == '__main__':
    unittest.main()
