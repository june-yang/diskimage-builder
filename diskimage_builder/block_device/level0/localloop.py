# Copyright 2016 Andreas Florath (andreas@florath.net)
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import logging
import os
import subprocess

from diskimage_builder.block_device.exception import \
    BlockDeviceSetupException
from diskimage_builder.block_device.plugin import NodeBase
from diskimage_builder.block_device.plugin import PluginBase
from diskimage_builder.block_device.utils import parse_abs_size_spec


logger = logging.getLogger(__name__)


class LocalLoopNode(NodeBase):
    """Level0: Local loop image device handling.

    This class handles local loop devices that can be used
    for VM image installation.
    """
    def __init__(self, config, default_config):
        logger.debug("Creating LocalLoop object; config [%s] "
                     "default_config [%s]", config, default_config)
        super(LocalLoopNode, self).__init__(config['name'])
        if 'size' in config:
            self.size = parse_abs_size_spec(config['size'])
            logger.debug("Image size [%s]", self.size)
        else:
            self.size = parse_abs_size_spec(default_config['image-size'])
            logger.debug("Using default image size [%s]", self.size)
        if 'directory' in config:
            self.image_dir = config['directory']
        else:
            self.image_dir = default_config['image-dir']
        self.filename = os.path.join(self.image_dir, self.name + ".raw")

    def get_edges(self):
        """Because this is created without base, there are no edges."""
        return ([], [])

    @staticmethod
    def image_create(filename, size):
        logger.info("Create image file [%s]", filename)
        with open(filename, "w") as fd:
            fd.seek(size - 1)
            fd.write("\0")

    @staticmethod
    def _image_delete(filename):
        logger.info("Remove image file [%s]", filename)
        os.remove(filename)

    @staticmethod
    def _loopdev_attach(filename):
        logger.info("loopdev attach")
        logger.debug("Calling [sudo losetup --show -f %s]", filename)
        subp = subprocess.Popen(["sudo", "losetup", "--show", "-f",
                                 filename], stdout=subprocess.PIPE)
        rval = subp.wait()
        if rval == 0:
            # [:-1]: Cut of the newline
            block_device = subp.stdout.read()[:-1].decode("utf-8")
            logger.info("New block device [%s]", block_device)
            return block_device
        else:
            logger.error("losetup failed")
            raise BlockDeviceSetupException("losetup failed")

    @staticmethod
    def _loopdev_detach(loopdev):
        logger.info("loopdev detach")
        # loopback dev may be tied up a bit by udev events triggered
        # by partition events
        for try_cnt in range(10, 1, -1):
            logger.debug("Calling [sudo losetup -d %s]", loopdev)
            subp = subprocess.Popen(["sudo", "losetup", "-d",
                                     loopdev])
            rval = subp.wait()
            if rval == 0:
                logger.info("Successfully detached [%s]", loopdev)
                return 0
            else:
                logger.error("loopdev detach failed")
                # Do not raise an error - maybe other cleanup methods
                # can at least do some more work.
        logger.debug("Gave up trying to detach [%s]", loopdev)
        return rval

    def create(self, state, rollback):
        logger.debug("[%s] Creating loop on [%s] with size [%d]",
                     self.name, self.filename, self.size)

        rollback.append(lambda: self._image_delete(self.filename))
        self.image_create(self.filename, self.size)

        block_device = self._loopdev_attach(self.filename)
        rollback.append(lambda: self._loopdev_detach(block_device))

        if 'blockdev' not in state:
            state['blockdev'] = {}

        state['blockdev'][self.name] = {"device": block_device,
                                        "image": self.filename}
        logger.debug("Created loop  name [%s] device [%s] image [%s]",
                     self.name, block_device, self.filename)
        return

    def umount(self, state):
        self._loopdev_detach(state['blockdev'][self.name]['device'])

    def cleanup(self, state):
        pass

    def delete(self, state):
        self._image_delete(state['blockdev'][self.name]['image'])


class LocalLoop(PluginBase):

    def __init__(self, config, defaults):
        super(LocalLoop, self).__init__()
        self.node = LocalLoopNode(config, defaults)

    def get_nodes(self):
        return [self.node]
