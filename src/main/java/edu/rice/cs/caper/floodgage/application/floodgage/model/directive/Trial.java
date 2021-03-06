/*
Copyright 2017 Rice University

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/
package edu.rice.cs.caper.floodgage.application.floodgage.model.directive;

import java.util.Collections;
import java.util.List;

public interface Trial
{
    String getDescription();

    String getDraftProgramPath();

    String getSketchProgramPath();

    List<Hole> getHoles();

    static Trial make(String description, String draftProgramPath, String sketchProgramPath, List<Hole> holes)
    {
        return new Trial()
        {
            @Override
            public String getDescription()
            {
                return description;
            }

            @Override
            public String getDraftProgramPath()
            {
                return draftProgramPath;
            }

            @Override
            public String getSketchProgramPath()
            {
                return sketchProgramPath;
            }

            @Override
            public List<Hole> getHoles()
            {
                return Collections.unmodifiableList(holes);
            }
        };
    }
}
