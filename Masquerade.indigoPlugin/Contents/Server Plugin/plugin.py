#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
## Python to interface with MyQ garage doors.
## based on https://github.com/Einstein42/myq-garage

import os
import plistlib
import sys
import time
import logging

from ghpu import GitHubPluginUpdater

kCurDevVersCount = 0        # current version of plugin devices

################################################################################
class Plugin(indigo.PluginBase):

    ########################################
    # Main Plugin methods
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))


    def startup(self):
        indigo.server.log(u"Starting Masquerade")

        self.masqueradeList = {}

        self.updater = GitHubPluginUpdater(self)
        self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "24")) * 60.0 * 60.0
        self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
        self.next_update_check = time.time()

        indigo.devices.subscribeToChanges()


    def shutdown(self):
        indigo.server.log(u"Shutting down Masquerade")


    def runConcurrentThread(self):

        try:
            while True:

                if self.updateFrequency > 0:
                    if time.time() > self.next_update_check:
                        self.updater.checkForUpdate()
                        self.next_update_check = time.time() + self.updateFrequency

                self.sleep(60.0)

        except self.stopThread:
            pass

    def deviceStartComm(self, device):

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers >= kCurDevVersCount:
            self.logger.debug(device.name + u": Device Version is up to date")
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps

            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            self.logger.debug(u"Updated " + device.name + " to version " + str(kCurDevVersCount))
        else:
            self.logger.error(u"Unknown device version: " + str(instanceVers) + " for device " + device.name)

        self.logger.debug("Adding Device %s (%d) to device list" % (device.name, device.id))
        assert device.id not in self.masqueradeList
        self.masqueradeList[device.id] = device

    def deviceStopComm(self, device):
        self.logger.debug("Removing Device %s (%d) from device list" % (device.name, device.id))
        assert device.id in self.masqueradeList
        del self.masqueradeList[device.id]


    ########################################
    # Menu Methods
    ########################################

    def checkForUpdates(self):
        self.updater.checkForUpdate()

    def updatePlugin(self):
        self.updater.update()

    def forceUpdate(self):
        self.updater.update(currentVersion='0.0.0')

    ########################################
    # ConfigUI methods
    ########################################

    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug(u"validatePrefsConfigUi called")
        errorDict = indigo.Dict()

        updateFrequency = int(valuesDict['updateFrequency'])
        if (updateFrequency < 0) or (updateFrequency > 24):
            errorDict['updateFrequency'] = u"Update frequency is invalid - enter a valid number (between 0 and 24)"

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)

        return (True, valuesDict)


    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))

            self.updateFrequency = float(self.pluginPrefs.get('updateFrequency', "24")) * 60.0 * 60.0
            self.logger.debug(u"updateFrequency = " + str(self.updateFrequency))
            self.next_update_check = time.time()

    ################################################################################
    #
    # delegate methods for indigo.devices.subscribeToChanges()
    #
    ################################################################################

    def deviceDeleted(self, delDevice):
        indigo.PluginBase.deviceDeleted(self, delDevice)

        for myDeviceId, myDevice in sorted(self.masqueradeList.iteritems()):
            baseDevice = int(myDevice.pluginProps["baseDevice"])
            if delDevice.id == baseDevice:
                self.logger.info(u"A device (%s) that was being Masqueraded has been deleted.  Disabling %s" % (delDevice.name, myDevice.name))
                indigo.device.enable(myDevice, value=False)   #disable it


    def deviceUpdated(self, oldDevice, newDevice):
        indigo.PluginBase.deviceUpdated(self, oldDevice, newDevice)

        for myDeviceId, myDevice in sorted(self.masqueradeList.iteritems()):
            baseDevice = int(myDevice.pluginProps["baseDevice"])
            if oldDevice.id == baseDevice:
                masqState = myDevice.pluginProps["masqState"]
                matchString = myDevice.pluginProps["matchString"]
                reverse = bool(myDevice.pluginProps["reverse"])

                if oldDevice.states[masqState] != newDevice.states[masqState]:
                    match = (str(newDevice.states[masqState]) == matchString)
                    if reverse:
                        match = not match
                    self.logger.debug(u"%s, a masqueraded device, has been updated: %s (%s)." % (oldDevice.name, myDevice.name, str(match)))
                    myDevice.updateStateOnServer(key='onOffState', value = match)

    ########################################################################
    # This method is called to generate a list of plugin identifiers / names
    ########################################################################
    def getPluginList(self, filter="", valuesDict=None, typeId="", targetId=0):
        retList = []
        indigoInstallPath = indigo.server.getInstallFolderPath()
        pluginFolders =['Plugins', 'Plugins (Disabled)']
        for pluginFolder in pluginFolders:
            pluginsList = os.listdir(indigoInstallPath + '/' + pluginFolder)
            for plugin in pluginsList:
                # Check for Indigo Plugins and exclude 'system' plugins
                if (plugin.lower().endswith('.indigoplugin')) and (not plugin[0:1] == '.'):
                    # retrieve plugin Info.plist file
                    pl = plistlib.readPlist(indigoInstallPath + "/" + pluginFolder + "/" + plugin + "/Contents/Info.plist")
                    bundleId = pl["CFBundleIdentifier"]
                    if self.pluginId != bundleId:
                        # Don't include self (i.e. this plugin) in the plugin list
                        displayName = pl["CFBundleDisplayName"]
                        # if disabled plugins folder, append 'Disabled' to name
                        if pluginFolder == 'Plugins (Disabled)':
                            displayName += ' [Disabled]'
                        retList.append((bundleId, displayName))

#        retList.sort(key=lambda tup: tup[1])
        return retList

    def getClassDevices(self, filter="", valuesDict=None, typeId="", targetId=0):
#        self.logger.debug(u"getClassDevices for: %s" % valuesDict["deviceClass"])

        retList = []

        deviceClass = valuesDict.get("deviceClass", None)
        if deviceClass != "plugin":
            for dev in indigo.devices.iter(deviceClass):
                retList.append((dev.id, dev.name))
        else:
            devicePlugin = valuesDict.get("devicePlugin", None)
#            self.logger.debug(u"getClassDevices: looking for devices for '%s'" % (devicePlugin))
            for dev in indigo.devices.iter():
                if dev.protocol == indigo.kProtocol.Plugin and dev.pluginId == devicePlugin:
                    for pluginId, pluginDict in dev.globalProps.iteritems():
                        pass
#                    self.logger.debug(u"PluginId of '%s' is '%s'" % (dev.name, unicode(pluginId)))
                    retList.append((dev.id, dev.name))

        retList.sort(key=lambda tup: tup[1])
        return retList

    def getStateList(self, filter="", valuesDict=None, typeId="", targetId=0):
#        self.logger.debug(u"getStateList for: %s" % valuesDict["baseDevice"])
        retList = []

        baseDeviceId = valuesDict.get("baseDevice", None)
        if not baseDeviceId:
            return retList

        baseDevice = indigo.devices[int(baseDeviceId)]

        for stateKey, stateValue in baseDevice.states.items():
            retList.append((stateKey, stateKey))
        retList.sort(key=lambda tup: tup[1])
        return retList

    # doesn't do anything, just needed to force other menus to dynamically refresh

    def menuChanged(self, valuesDict, typeId, devId):
 #       self.logger.debug(u"menuChanged: typeId = %s, devId = %s" % (unicode(typeId), unicode(devId)))
        return valuesDict

