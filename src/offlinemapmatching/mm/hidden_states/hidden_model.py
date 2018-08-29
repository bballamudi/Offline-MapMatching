from ..observation.network import *
from ..observation.trajectory import *
from ..observation.observation import *
from .candidate import *
from .transition import *
from qgis.core import *
import os
from PyQt5.QtWidgets import QProgressBar, QApplication
from PyQt5.QtCore import QVariant, QDir

class HiddenModel:
    
    def __init__(self, trajectory, network):
        self.trajectory = trajectory
        self.network = network
        self.counter_candidates = 0
        self.candidate_graph = []
        self.candidates = {}
        self.candidates_backtracking = {}
        self.pb = None
    
    def createGraph(self, sigma, my, maximum_distance):
        #init progressbar
        self.initProgressbar(len(self.trajectory.observations))
        
        #init data structur
        self.candidate_graph = []
        self.candidates = {}
        self.counter_candidates = 0
        
        #iterate over all observations from our trajectory
        for observation in self.trajectory.observations:
            
            #extract all candidates of the current observation
            candidates = observation.getCandidates(self.network.vector_layer, maximum_distance)
            if len(candidates) == 0:
                return -5
            else:
                #create the current level of the trellis
                current_trellis_level = []
                for candidate in candidates:
                    candidate.calculateEmissionProbability(observation, sigma, my)
                    current_trellis_level.append({'id' : str(self.counter_candidates),
                                                  'observation_id' : observation.id,
                                                  'emitted_probability' : candidate.emission_probability,
                                                  'transition_probabilities' : {},
                                                  'transition_probability' : 0.0,
                                                  'total_probability' : 0.0})
                    self.candidates.update({str(self.counter_candidates) : candidate})
                    self.counter_candidates += 1
                
                #normalise the probabilities and add the current trellis level to the trellis
                self.candidate_graph.append(current_trellis_level)
            
            #update progressbar
            self.updateProgressbar()
            
        return 0
    
    def getTrellisEntryById(self, id, level):
        for entry in self.candidate_graph[level]:
            if entry.get('id') == id:
                return entry
    
    def createBacktracking(self):
        #init progressbar
        self.initProgressbar(len(self.candidate_graph))
        
        self.candidates_backtracking = {}
        
        for i, trellis_level in enumerate(self.candidate_graph):
            
            #the candidates of the first observation have no parent
            if i != 0:
                for entry in trellis_level:
                    
                    #get all transition probabilities of the current entry and iterate over them to find the highest total probability
                    transition_probabilities = entry.get('transition_probabilities')
                    for key in transition_probabilities:
                        current_total_probability = transition_probabilities.get(key) * entry.get('emitted_probability') * self.getTrellisEntryById(key, i - 1).get('total_probability')
                        if current_total_probability > entry.get('total_probability'):
                            entry.update({'total_probability' : current_total_probability})
                            entry.update({'transition_probability' : transition_probabilities.get(key)})
                            self.candidates_backtracking.update({entry.get('id') : key})
            
            #update progressbar
            self.updateProgressbar()
        
        return 0
    
    def findViterbiPath(self):
        #init an array to store all candidates of the most likely path
        viterbi_path = []
        
        #find the highest total probability in the last trellis level
        highest_prob = 0.0
        id = None
        trellis_counter = len(self.candidate_graph) - 1
        last_trellis_level = self.candidate_graph[trellis_counter]
        for entry in last_trellis_level:
            if entry.get('total_probability') >= highest_prob:
                highest_prob = entry.get('total_probability')
                id = entry.get('id')
        
        #add the last vertex of the path
        viterbi_path.insert(0, {'vertex': self.candidates.get(id),
                                'total_probability': highest_prob,
                                'emitted_probability': self.getTrellisEntryById(id, trellis_counter).get('emitted_probability'),
                                'transition_probability': self.getTrellisEntryById(id, trellis_counter).get('transition_probability'),
                                'observation_id': trellis_counter})
        
        #now find all parents of this vertex/candidate
        trellis_counter -= 1
        current_id = self.candidates_backtracking.get(id)
        while(current_id is not None and trellis_counter >= 0):
            searched_candidate = self.getTrellisEntryById(current_id, trellis_counter)
            viterbi_path.insert(0, {'vertex': self.candidates.get(current_id),
                                    'total_probability': searched_candidate.get('total_probability'),
                                    'emitted_probability': searched_candidate.get('emitted_probability'),
                                    'transition_probability': searched_candidate.get('transition_probability'),
                                    'observation_id': trellis_counter})
            current_id = self.candidates_backtracking.get(current_id)
            trellis_counter -= 1
        
        return viterbi_path
    
    def setTransitionProbabilities(self):
        #init progressbar
        self.initProgressbar(len(self.trajectory.observations))
        
        for i, observation in enumerate(self.trajectory.observations):
            
            #skip the first observation, because first observation has no parent
            if i != 0:
                
                #get the current and previous trellis level
                previous_trellis_level = self.candidate_graph[i - 1]
                current_trellis_level = self.candidate_graph[i]
                
                for previous_entry in previous_trellis_level:
                    
                    #init a variable to store the sum of transition probabilities starting from the previous_entry
                    #to create a right stochastic matrix (that's not right, normalisation is commended!)
                    sum_prob = 0.0
                    
                    for current_entry in current_trellis_level:
                        
                        #get the candidates
                        current_candidate = self.candidates.get(current_entry.get('id'))
                        previous_candidate = self.candidates.get(previous_entry.get('id'))
                        
                        #just continue, if both candidates do not have the same position, otherwise probability is equal zero
                        if self.checkPositionsOfTwoCandidates(current_candidate, previous_candidate):
                            transition = Transition(previous_candidate, current_candidate)
                            
                            #calculate the probabilities of the transition
                            transition.setDirectionProbability(self.trajectory.observations[i - 1], observation)
                            transition.setRoutingProbability(self.network, observation.point.distance(self.trajectory.observations[i - 1].point))
                            transition.setTransitionProbability()
                            
                            #insert the probability into the trellis and sum up them
                            sum_prob += transition.transition_probability
                            current_entry.get('transition_probabilities').update({previous_entry.get('id') : transition.transition_probability})
                
            self.updateProgressbar()
            
        return 0
    
    def checkPositionsOfTwoCandidates(self, candidate_1, candidate_2):
        #get coordinates of the previous entry and the current candidate
        x_candidate_1 = candidate_1.point.asPoint().x()
        y_candidate_1 = candidate_1.point.asPoint().y()
        x_candidate_2 = candidate_2.point.asPoint().x()
        y_candidate_2 = candidate_2.point.asPoint().y()
                        
        #if points are not equal, return True, otherwise False
        if x_candidate_1 != x_candidate_2 and y_candidate_1 != y_candidate_2:
            return True
        else:
            return False
    
    def setStartingProbabilities(self):
        first_tellis_level = self.candidate_graph[0]
        
        #init progressbar
        self.initProgressbar(len(first_tellis_level))
        
        for entry in first_tellis_level:
            entry.update({'total_probability' : entry.get('emitted_probability')})
            self.candidates_backtracking.update({entry.get('id') : None})
            self.updateProgressbar()
        
        return 0
    
    def addFeaturesToLayer(self, features, attributes, crs):
        #create a new layer
        layer = QgsVectorLayer('LineString?crs=' + crs + '&index=yes', 'matched trajectory', 'memory')
        
        #load the layer style
        dir = os.path.dirname(__file__)
        filename = os.path.abspath(os.path.join(dir, '..', '..', 'style.qml'))
        layer.loadNamedStyle(filename, loadFromLocalDb=False)
        
        #add the layer to the project
        layer.startEditing()
        layer_data = layer.dataProvider()
        layer_data.addAttributes(attributes)
        layer.updateFields()
        
        #add features to the layer
        layer.addFeatures([feature])
        layer.commitChanges()
    
        #add the layer to the map
        QgsProject.instance().addMapLayer(layer)
        
        return layer
    
    def getPathOnNetwork(self, vertices):
        #init progressbar
        self.initProgressbar(len(vertices))
        
        #create an array to store all features
        features = []
        
        #iterate over the vertices
        for i, vertex in enumerate(vertices):
            
            #if we are in the first loop, we skip them because we have no previous point to create a routing with start and end
            if i != 0:
                
                #get all edges of the graph/network along the shortest way from the previous to the current vertex
                points = self.network.routing(vertices[i - 1]['vertex'].point.asPoint(), vertex['vertex'].point.asPoint())
                
                if points == -1:
                    return points
                
                #now create a new line feature
                feature = QgsFeature(layer.fields())
                
                #create the geometry of the new feature
                feature.setGeometry(QgsGeometry.fromPolylineXY(points))
                
                #insert the attributes and add the feature to the layer
                feature.setAttribute('id', i)
                feature.setAttribute('total_probability_start', vertices[i - 1]['total_probability'])
                feature.setAttribute('total_probability_end', vertex['total_probability'])
                feature.setAttribute('emission_probability_start', vertices[i - 1]['emitted_probability'])
                feature.setAttribute('emission_probability_end', vertex['emitted_probability'])
                feature.setAttribute('transition_probability_start', vertices[i - 1]['transition_probability'])
                feature.setAttribute('transition_probability_end', vertex['transition_probability'])
                feature.setAttribute('observation_id_start', vertices[i - 1]['observation_id'])
                feature.setAttribute('observation_id_end', vertex['observation_id'])
                features.append(feature)
            
            self.updateProgressbar()
        
        return features
    
    def initProgressbar(self, maximum):
        if self.pb is not None:
            self.pb.setValue(0)
            self.pb.setMaximum(maximum)
            QApplication.processEvents()
    
    def updateProgressbar(self):
        if self.pb is not None:
            self.pb.setValue(self.pb.value() + 1)
            QApplication.processEvents()
    
