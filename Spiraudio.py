"""
Code written by Roger Fachini for RoboGames 2015. 
Licensed under the GNU General Public License (see LICENSE.md) 
"""

#Global settings and constants stored here
class Config:
    CNCSERVER_ARGS = "--botType=eggbot" #Any arguments to send to CNCServer on startup. 

    AUDIO_FILE = 'audio/test.wav' #The audio file to play when the 'Play from File' option  is selected

    CNCSERVER_ADDRESS = 'http://localhost:4242' #Change for an external CNCServer

    PAPER_RATIO = (9.0, 12.0)     #Ratio of the printing canvas (defaults to 9x12). MUST be a float
    PAPER_SIZE = 500              #Canvas size in pixels 

    SAMPLE_TICK_MS = 10           #Interval, in ms, to sample the audio and draw a point. 

    BUFFER_INCREMENT_MIC = 0.05   #How much to increment the audio graph by. 
    BUFFER_INCREMENT_FILE = 0.01  

    VISUAL_OFFSET_MIC = 1000.0    #The smaller these are, the larger the audio spike will be on the spiral
    VISUAL_OFFSET_FILE = 2500.0

    SPIRAL_ARC = 1                #Controls the size inbetween points on the spiral
    SPIRAL_SIZE = 15              #Controls the distance between loops of the spiral

    AUDIO_SAMPLE_RATE = 5000      #Number of audio samples per frame for the microphone
    INPUT_BLOCK_TIME = 0.005      #Time in seconds of each microphone sample


#Import builtin modules first
import math, time, datetime
import logging, os, subprocess, threading, platform, struct, json

#Import dependencies in a try statement to give a more user-friendly error message
try:  
    import pygame
    from pygame.locals import *  
    import pyaudio
    import requests
except ImportError as er:
    print 'ERROR: One or more dependencies not met. \n',er
    time.sleep(2)
    exit()


class Audio:
    """
    Gathers audio samples from different sources, based on OS type and method selected
    """
    inputType = 'n'         #Type of audio source. 'n' for none, 'm' for microphone, and 'f' for file. 
    isRecording = False     #used to tell if the audio sample is currently active. 
    def __init__(self):
        #Create logging instance
        self.logger = logging.getLogger('Audio')        
        self.logger.info('Created audio stream handler')
        
        #The current audio buffer
        self.currentSample = []       
        
        #instantiate PyAudio instance
        self.pyaudio = pyaudio.PyAudio()   
        
        #Calculate the sample rate for the microphone input                           
        self.INPUT_FRAMES= int(Config.AUDIO_SAMPLE_RATE * Config.INPUT_BLOCK_TIME)
        self.logger.debug('Created PyAudio instance')  
        
    def setInputToFile(self, file):
        """
        Set the input source to the specified file. 
        Supported file types include OGG, XM, WAV, and MOD. MP3 support is limited, so beware
        """
        self.AUDIO_RATE = 22050      
        #Stop a currently playing audio file if there is one          
        if self.inputType == 'f': self.stream.stop()

        #Initalize the audio playback module
        pygame.mixer.init(self.AUDIO_RATE, -16, 2, 2048)

        #Load the file, start playback,  and get the raw data
        soundObj = pygame.mixer.Sound(file)
        self.soundData = pygame.sndarray.array(soundObj)
        self.stream = soundObj.play()
        self.startTime = time.clock()

        #Set the command to read the audio to the appropriate subroutine
        self.streamCommand = self._fileRead

        self.inputType = 'f'
        self.logger.info('Set input source to FILE. Currently Playing: %s',file)
        
    def setInputToMicrophone(self):
        """
        Set the input source to record from a microphone
        """
        #Stop a currently playing audio file if there is one    
        if self.inputType == 'f': self.stream.stop()

        #Start a new audio stream from the microphone
        self.startTime = time.clock()     
        self.stream = self.pyaudio.open(format = pyaudio.paInt16,                      
                                        channels = 1,                          
                                        rate = Config.AUDIO_SAMPLE_RATE,                                  
                                        input = True,                                 
                                        frames_per_buffer = self.INPUT_FRAMES)  

        #Set the command to read the audio to the appropriate subroutine 
        self.streamCommand = self._microphoneStreamRead
        self.inputType = 'm'
        self.logger.info('Set input source to MICROPHONE')

    def setInputToNone(self):
        """
        Set the input source to none, effectively stopping any recording. 
        """
        #Stop a currently playing audio file if there is one   
        if self.inputType == 'f': self.stream.stop()

        #Reset the status variables to reflect a state of no audio playing
        self.isRecording = False
        self.inputType = 'n'
        self.timeNow = 0

        #Set the command to read the audio to a subroutine that returns nothing
        def null(): return []
        self.streamCommand = null

        self.logger.info('Set input source to NONE.')

    def getCurrentSample(self):
        """
        Get the latest audio packet and return it. 
        """
        #Call the subroutine set to read the current audio packet
        self.currentSample = self.streamCommand()
        return self.currentSample

    def _microphoneStreamRead(self):
        #Update the current sample time
        self.timeNow = time.clock() - self.startTime
        try:
            #Read a block of audio and unpack it
            block = self.stream.read(self.INPUT_FRAMES)  
            count = len(block)/2
            format = "%dh"%(count)
            shorts = struct.unpack(format, block)
        except IOError as error:
            #Return an empty sample in the case of an error
            shorts = [0]
        return shorts

    def _fileRead(self):
        #Update the current sample time and the playing status
        self.timeNow = time.clock() - self.startTime
        self.isRecording = self.stream.get_busy()

        #Return an empty sample if there is no sample left
        if not self.isRecording: 
            return []
        #Create a pointer from the current time
        pointer = int(self.AUDIO_RATE*self.timeNow)      

        #Read the last thirty audio samples
        data = self.soundData[pointer-30:pointer]

        #Only return the left channel 
        data = [d[0] for d in data]
        return data 


class Visuals:
    """
    Converts audio samples into pretty spiral patterns
    """
    pointA = (0,0) #The current point, with the audio mixed in
    pointC = (0,0) #The current point, without the audio                  
    inputType = 'n'
    def p2c(self, dist, angle):
        """Converts between polar and cartesian coordinate systems"""
        return (dist * math.cos(angle), dist * math.sin(angle))

    def spiral_points(self, arc=1, size=5):
        """
        Resets the spiral and starts it off. 
        """
        #Clear the two point variables
        self.pointA = (0,0)  
        self.pointC = (0,0)

        self.arc = arc
        self.dist = arc
        self.b = size / math.pi
        self.angle = float(self.dist) / self.b

    def increment_spiral(self, offset):
        """
        Resets the spiral and starts it off. 
        """
        #Determine the adjustment factor by the config
        if self.inputType == 'f':   adj = offset / Config.VISUAL_OFFSET_FILE
        elif self.inputType == 'm': adj = offset / Config.VISUAL_OFFSET_MIC
        else: return

        #Calculate both the audio point and the clean point
        self.pointA = self.p2c(self.dist + adj, self.angle)
        self.pointC = self.p2c(self.dist, self.angle)

        #Increment the angle
        self.angle += float(self.arc) / self.dist

        #Recalculate the spiral
        self.dist = self.b * self.angle / 2
        
class CNCServerClient:
    """
    Connects to CNCServer and sends commands to the WaterColorBot for drawing purpouses
    """
    hasConnection = False
    def __init__(self):
        #Create Logging instance
        self.logger = logging.getLogger('CNCClient')
        self.logger.debug('Client instance created!')
        try:
            r = requests.get(Config.CNCSERVER_ADDRESS+'/v1/settings/global',  timeout = 1)
            self.hasConnection = True
        except requests.exceptions.ConnectionError as er:
            self.logger.critical('Could not create connection to external server!')
            self.hasConnection = False
            if self.launchCncServer():
                self.hasConnection = True

    def setPenPos(self,x,y):
        if not self.hasConnection: return 
        data = {'x':str(x),'y':str(y)}
        data_json = json.dumps(data)
        try:
            r = requests.put(Config.CNCSERVER_ADDRESS+'/v1/pen/', data=data, timeout = 0.01)
        except requests.exceptions.ReadTimeout:
            pass
        
    def setPenPosScaled(self,pos,size):
        x = 100*(pos[0]/float(size[0]))
        y = 100*(pos[1]/float(size[1]))
        self.setPenPos(x,y)

    def launchCncServer(self):
        if os.path.exists("cncserver/cncserver.js"):
            self.logger.info('Built-In CNCServer exists!')
            self.serverProcess = subprocess.Popen(['node', 'cncserver.js', Config.CNCSERVER_ARGS], 
                                                  stdout=subprocess.PIPE,
                                                  cwd = 'cncserver')
            serverLog = logging.getLogger('CNCServer')
            self.loggigngThread = threading.Thread(target=self._outputHandlingThread,
                                                   args = (serverLog, self.serverProcess,))
            self.loggigngThread.start()
            #self.hasConnection = True
        else:
            self.logger.error('CNCServer not found at ../cncserver/cncserver.js')

    def _outputHandlingThread(self,logger, serverInstance):
        while True:
            line = serverInstance.stdout.readline().replace('\n','')
            if 'is ready to receive commands' in line:
                self.hasConnection = True
            logger.info(line)
            
class Display:
    """
    The  Graphical Interface, which displays information about the current sample and output
    """
    graphIndex = 0
    audioBuffer = []
    pointlistA = [(0,0)]
    pointlistC = []
    lastBufferPoint = 0
    inputType = 'n'
    drawTracer = False
    def __init__(self):
        self.logger = logging.getLogger('GUI')
        pygame.init()
        self.logger.debug('Pygame initalization complete')
        
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont('consolas',12)
        self.logger.debug('Font objects created')

        pygame.display.set_caption('WaterColorBot Spiral Audio Paint')

        ratio = Config.PAPER_RATIO[1]/Config.PAPER_RATIO[0]
        size = (int(Config.PAPER_SIZE*ratio),Config.PAPER_SIZE)

        pygame.time.set_timer(USEREVENT,Config.SAMPLE_TICK_MS)

        self.SurfCanvas = pygame.Surface(size)
        self.SurfCanvas.fill((255,255,255))
        self.SurfGraph = pygame.Surface((420,100))
        self.pointlistC.append(self._convertCanvasOffset((0,0)))

        self.logger.debug('Created Canvas surface with size %s and ratio %s',size,ratio)

        self.vis = Visuals()

        self.display = pygame.display.set_mode((1150,530))
  
    def handle_event(self, event):
        if event.type == QUIT:
            pygame.quit()
            quit()

        elif event.type == KEYDOWN:
            if event.unicode == 'm':
                input.setInputToMicrophone()
            elif event.unicode == 'f':
                input.setInputToFile(Config.AUDIO_FILE)
            elif event.unicode == 'n':
                input.setInputToNone()
            elif event.unicode == 'c':
                self.clearCanvas()
            elif event.unicode == 't':
                self.drawTracer = not self.drawTracer
                
            gui.inputType = input.inputType
            gui.vis.inputType = input.inputType

        elif event.type == USEREVENT:
            points = self.audioBuffer[self.lastBufferPoint:]
            try:
                avg = sum(points)/len(points)
                self.vis.increment_spiral(avg)
            except ZeroDivisionError:
                pass
            
            self.lastBufferPoint = len(self.audioBuffer)
            pygame.event.clear(USEREVENT)
        
    def update(self, fps=0):
        e = pygame.event.poll()
        self.handle_event(e)
        self.display.fill((25,25,25))
        self.render_canvas()

        self.display.blit(self.SurfCanvas, (5,20))
        self.display.blit(self.SurfGraph, (700,20))
        r = self.font.render('WaterColorBot Canvas',1, (255,255,255))
        self.display.blit(r,(5,5))

        r = self.font.render('Input Audio',1, (255,255,255))
        self.display.blit(r,(730,5))

        self.render_status()
        pygame.display.update()
        self.clock.tick(fps)

    def render_status(self):
        r = self.font.render('SPS: %s'%int(self.clock.get_fps()),1, (255,255,255))
        self.display.blit(r,(700,120))

        r = self.font.render('Sample Time: '+str(datetime.timedelta(seconds=self.recordingTime)),1, (255,255,255))
        self.display.blit(r,(800,120))

        r = self.font.render('Keys:',1, (255,255,255))
        self.display.blit(r,(700,140))
        r = self.font.render('  m - Change input to microphone',1, (255,255,255))
        self.display.blit(r,(700,150))
        r = self.font.render('  f - Change input to file',1, (255,255,255))
        self.display.blit(r,(700,160))
        r = self.font.render('  n - Change inpit to none',1, (255,255,255))
        self.display.blit(r,(700,170))
        r = self.font.render('  c - Clear canvas and audio buffers',1, (255,255,255))
        self.display.blit(r,(700,180))
        self.display.blit(self.font.render('  t - Toggle drawing red line on perfect spiral',1, (255,255,255)),(700,190))

        if self.inputType == 'm': text = 'Input Type: MICROPHONE'
        elif self.inputType == 'f': text = 'Input Type: FILE'
        elif self.inputType == 'n': text = 'Input Type: NONE'
        self.display.blit(self.font.render(text,1, (255,255,255)),(700,210))

        if self.drawTracer: text = 'Draw Tracer: True'
        else: text = 'Draw Tracer: False'
        self.display.blit(self.font.render(text,1, (255,255,255)),(700,220))
    
    def render_canvas(self):
        #self.SurfCanvas.fill((255,255,255))
        x = int(self.vis.pointA[0])
        y = int(self.vis.pointA[1])
        self.pointlistA.append((x,y))
        bot.setPenPosScaled(self._convertCanvasOffset((x,y)),
                            self.SurfCanvas.get_size())

        x = int(self.vis.pointC[0])
        y = int(self.vis.pointC[1])
        self.pointlistC.append(self._convertCanvasOffset((x,y)))
        
        points = [self._convertCanvasOffset(p) for p in self.pointlistA]

        
        pygame.draw.lines(self.SurfCanvas, (0,0,255), False, points[-2:],2)
        if self.drawTracer:
            try: pygame.draw.lines(self.SurfCanvas, (255,0,0), False, self.pointlistC[-2:])
            except ValueError:  pass
          
    def RenderAudioGraphPoint(self, point):
        p = point/700+50
        self.SurfGraph.set_at((int(self.graphIndex),p),(0,0,255))
        if self.inputType == 'f':
            self.graphIndex += Config.BUFFER_INCREMENT_FILE
        elif self.inputType == 'm':
            self.graphIndex += Config.BUFFER_INCREMENT_MIC
        
        if self.graphIndex > 420:
            self.graphIndex = 0
            self.SurfGraph.fill((0,0,0))
            self.audioBuffer = [self.audioBuffer[-1]]

    def _convertCanvasOffset(self, p):
        x = p[0] + self.SurfCanvas.get_width() / 2
        y = p[1] + self.SurfCanvas.get_height() / 2
        return (x,y)

    def clearCanvas(self):
        input.setInputToNone()
        gui.vis.spiral_points(Config.SPIRAL_ARC,
                          Config.SPIRAL_SIZE)
        self.audioBuffer = []
        self.graphIndex = 0
        self.lastBufferPoint = 0
        self.pointlistA = [(0,0)]
        self.pointlistC = []
        self.SurfCanvas.fill((255,255,255))
        self.SurfGraph.fill((0,0,0))
        bot.setPenPos(50,50)
        self.logger.info('Cleared Canvas!')
        
        
if __name__ == '__main__':
    #Configure logging module and supress debug info from requests
    logging.basicConfig(level=logging.DEBUG,
                        format='[%(levelname)-8s] [%(name)s] %(message)s') 
    logging.getLogger("requests").setLevel(logging.WARNING)

    bot = CNCServerClient()
    bot.setPenPos(50,50)

    input = Audio()
    #input.setInputToMicrophone()
    #input.setInputToFile(Config.AUDIO_FILE)
    input.setInputToNone()

    gui = Display()
    gui.vis.spiral_points(Config.SPIRAL_ARC,
                          Config.SPIRAL_SIZE)

   
    while True:
        a = input.getCurrentSample()
        for point in a:
            gui.audioBuffer.append(point)
            gui.RenderAudioGraphPoint(point)
        gui.recordingTime = input.timeNow
        gui.update()